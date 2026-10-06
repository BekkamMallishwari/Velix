import contextlib
import os
import platform
import resource
import signal
import subprocess
import tempfile
import threading
import typing

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult

logger = get_logger("sandbox.macos")


class MacOSSandboxBackend(SandboxBackend):
    @classmethod
    def get_capabilities(cls) -> SandboxCapabilities:
        return SandboxCapabilities(
            filesystem_isolation="SUPPORTED",
            network_isolation="SUPPORTED",
            cpu_limit="SUPPORTED",
            memory_limit="UNSUPPORTED",
            process_limit="UNSUPPORTED",
            timeout="SUPPORTED",
            output_limit="SUPPORTED",
            secret_filtering="SUPPORTED",
        )

    def _generate_profile(self, policy: SandboxPolicy) -> str:
        home = os.environ.get("HOME", "/tmp")
        profile = [
            "(version 1)",
            "(deny default)",
            '(import "system.sb")',
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow file-read-metadata)",
            "(deny file-read*",
            '    (literal "/etc/passwd")',
            '    (literal "/private/etc/passwd")',
            '    (literal "/private/etc/master.passwd")',
            f'    (subpath "{home}/.ssh")',
            f'    (subpath "{home}/.aws")',
            f'    (subpath "{home}/.config")',
            ")",
        ]

        profile.append("(allow file-read*")
        profile.append('    (subpath "/bin")')
        profile.append('    (subpath "/usr/bin")')
        profile.append('    (subpath "/usr/lib")')
        profile.append('    (subpath "/System")')
        profile.append('    (subpath "/Library")')
        profile.append('    (subpath "/private/var/select")')

        import sys
        base_prefix = os.path.realpath(sys.base_prefix)
        prefix = os.path.realpath(sys.prefix)
        profile.append(f'    (subpath "{base_prefix}")')
        if prefix != base_prefix:
            profile.append(f'    (subpath "{prefix}")')
        profile.append('    (subpath "/private/etc/ssl")')
        profile.append('    (subpath "/etc/ssl")')
        profile.append('    (literal "/dev/urandom")')
        profile.append('    (literal "/dev/random")')
        profile.append(")")

        profile.append("(allow file-read* file-write*")
        profile.append('    (subpath "/tmp")')
        profile.append('    (subpath "/private/tmp")')
        profile.append('    (literal "/dev/null")')
        profile.append('    (literal "/dev/zero")')
        profile.append(")")

        workspace_path = policy.workspace_root.resolve().as_posix()
        profile.append(f'(allow file-read* file-write* (subpath "{workspace_path}"))')
        profile.append(f'(deny file-read* file-write* (subpath "{workspace_path}/.git"))')

        if not policy.allow_network:
            profile.append("(deny network*)")

        return "\n".join(profile)

    MAX_OUTPUT_BYTES = 50_000

    @staticmethod
    def _read_stream(
        stream: typing.IO[bytes],
        chunks_list: list[bytes],
        truncated_flag: list[bool]
    ) -> None:
        total_bytes = 0
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break

            if total_bytes < MacOSSandboxBackend.MAX_OUTPUT_BYTES:
                remaining = MacOSSandboxBackend.MAX_OUTPUT_BYTES - total_bytes
                chunks_list.append(chunk[:remaining])
                total_bytes += len(chunk)
                if len(chunk) > remaining:
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True

    def execute(
        self, command: list[str], policy: SandboxPolicy, timeout: int = 30
    ) -> SandboxResult:
        if platform.system() != "Darwin":
            raise SandboxError("MacOSSandboxBackend is only available on macOS.")

        profile_content = self._generate_profile(policy)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as f:
            f.write(profile_content)
            profile_path = f.name

        def set_limits() -> None:
            # CPU Limit: Process receives SIGXCPU if it uses more than `timeout` seconds.
            # We use preexec_fn as it is the only practical mechanism on macOS to enforce
            # RLIMIT_CPU on the child before execve.
            with contextlib.suppress(Exception):
                resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))

            # Note on Process Limits (RLIMIT_NPROC):
            # RLIMIT_NPROC is per-user on macOS. Enforcing a low limit here restricts the
            # entire user session, often instantly breaking execution if the user already
            # has >100 processes running (e.g. Chrome, IDEs). We omit RLIMIT_NPROC and rely
            # entirely on the killpg timeout cleanup to reap runaway processes instead.

            # Note on Memory Limits (RLIMIT_AS / RLIMIT_DATA):
            # They cannot be reliably enforced without breaking `execve` (crashing
            # CoreFoundation or the Python interpreter immediately upon launch).
            pass

        try:
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
                "HOME": os.environ.get("HOME", "/tmp"),
                "USER": os.environ.get("USER", "nobody"),
            }

            sandbox_cmd = ["sandbox-exec", "-f", profile_path, *command]

            logger.info(f"Executing sandboxed command: {' '.join(command)}")

            process = subprocess.Popen(
                sandbox_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=policy.workspace_root.as_posix(),
                start_new_session=True,  # Isolate process group to kill runaway children
                preexec_fn=set_limits
            )

            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_truncated = [False]
            stderr_truncated = [False]

            out_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stdout, stdout_chunks, stdout_truncated)
            )
            err_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stderr, stderr_chunks, stderr_truncated)
            )
            out_thread.daemon = True
            err_thread.daemon = True
            out_thread.start()
            err_thread.start()

            timeout_expired = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timeout_expired = True
                with contextlib.suppress(Exception):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()

            out_thread.join()
            err_thread.join()

            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            if stdout_truncated[0]:
                stdout_str += "\\n...[TRUNCATED: Output exceeded maximum size limit]..."
            if stderr_truncated[0]:
                stderr_str += "\\n...[TRUNCATED: Output exceeded maximum size limit]..."

            if timeout_expired:
                return SandboxResult(
                    stdout="", stderr="Command timed out", exit_code=-1, command=command
                )

            return SandboxResult(
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode,
                command=command,
            )
        except Exception as e:
            raise SandboxError(f"Failed to execute sandboxed command: {e}") from e
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)
