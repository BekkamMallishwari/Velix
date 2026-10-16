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
            disk_limit="UNSUPPORTED",
            runtime_isolation="UNSUPPORTED",
            observability="UNSUPPORTED",
            security_hardening="UNSUPPORTED",
        )

    @staticmethod
    def _escape_seatbelt_path(path: str) -> str:
        """Escape special characters in a path for Seatbelt scheme profile literals.

        In Seatbelt S-expressions, string literals are enclosed in double quotes.
        Backslashes and double quotes must be escaped. Control characters like newlines
        must be removed to prevent breaking out of string literals or rule injection.
        """
        return path.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "").replace("\r", "")

    def _generate_profile(self, policy: SandboxPolicy) -> str:
        home = os.environ.get("HOME", policy.workspace_root.as_posix())
        home_paths = {home, os.path.realpath(home)}

        deny_rules = [
            '    (literal "/etc/passwd")',
            '    (literal "/private/etc/passwd")',
            '    (literal "/private/etc/master.passwd")',
        ]
        for h in sorted(home_paths):
            escaped_h = self._escape_seatbelt_path(h)
            deny_rules.extend([
                f'    (subpath "{escaped_h}/.ssh")',
                f'    (subpath "{escaped_h}/.aws")',
                f'    (subpath "{escaped_h}/.config")',
            ])

        profile = [
            "(version 1)",
            "(deny default)",
            '(import "system.sb")',
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow file-read-metadata)",
            "(deny file-read*",
            *deny_rules,
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

        prefixes = {
            sys.base_prefix,
            os.path.realpath(sys.base_prefix),
            sys.prefix,
            os.path.realpath(sys.prefix),
        }
        for p in sorted(prefixes):
            escaped_p = self._escape_seatbelt_path(p)
            profile.append(f'    (subpath "{escaped_p}")')

        profile.append('    (subpath "/private/etc/ssl")')
        profile.append('    (subpath "/etc/ssl")')
        profile.append('    (literal "/dev/urandom")')
        profile.append('    (literal "/dev/random")')
        profile.append(")")

        profile.append("(allow file-read* file-write*")
        profile.append('    (literal "/dev/null")')
        profile.append('    (literal "/dev/zero")')
        profile.append(")")

        workspace_resolved = policy.workspace_root.resolve().as_posix()
        escaped_resolved = self._escape_seatbelt_path(workspace_resolved)
        profile.append(f'(allow file-read* file-write* (subpath "{escaped_resolved}"))')
        profile.append(f'(deny file-read* file-write* (subpath "{escaped_resolved}/.git"))')
        workspace_raw = policy.workspace_root.as_posix()
        if workspace_raw != workspace_resolved:
            escaped_raw = self._escape_seatbelt_path(workspace_raw)
            profile.append(f'(allow file-read* file-write* (subpath "{escaped_raw}"))')
            profile.append(f'(deny file-read* file-write* (subpath "{escaped_raw}/.git"))')

        if not policy.allow_network:
            profile.append("(deny network*)")

        return "\n".join(profile)

    MAX_OUTPUT_BYTES = 50_000

    @staticmethod
    def _read_stream(
        stream: typing.IO[bytes],
        chunks_list: list[bytes],
        truncated_flag: list[bool],
        max_bytes: int = 50_000,
    ) -> None:
        total_bytes = 0
        read_fn = getattr(stream, "read1", stream.read)
        while True:
            chunk = read_fn(4096)
            if not chunk:
                break

            if total_bytes < max_bytes:
                remaining = max_bytes - total_bytes
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

        if policy.max_output_size < 0:
            raise SandboxError(
                f"max_output_size must be non-negative, got {policy.max_output_size}"
            )

        profile_content = self._generate_profile(policy)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as f:
            f.write(profile_content)
            profile_path = f.name

        def set_limits() -> None:
            # CPU Limit: Process receives SIGXCPU if it uses more than `timeout` seconds.
            # We use preexec_fn as it is the only practical mechanism on macOS to enforce
            # RLIMIT_CPU on the child before execve.
            if policy.cpu_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))  # type: ignore[attr-defined]

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
                "HOME": os.environ.get("HOME", policy.workspace_root.as_posix()),
                "USER": os.environ.get("USER", "nobody"),
            }
            env.update(policy.env)

            sandbox_cmd = ["sandbox-exec", "-f", profile_path, *command]

            logger.info(f"Executing sandboxed command: {' '.join(command)}")

            process = subprocess.Popen(
                sandbox_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=policy.workspace_root.as_posix(),
                start_new_session=True,  # Isolate process group to kill runaway children
                preexec_fn=set_limits,
            )

            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_truncated = [False]
            stderr_truncated = [False]

            out_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stdout, stdout_chunks, stdout_truncated, policy.max_output_size),
            )
            err_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stderr, stderr_chunks, stderr_truncated, policy.max_output_size),
            )
            out_thread.daemon = True
            err_thread.daemon = True
            out_thread.start()
            err_thread.start()

            def _terminate_process_tree(root_pid: int) -> None:
                """Terminate root process and all discoverable descendants.

                On macOS, Darwin lacks kernel-level PID namespaces or Job Objects.
                A child that calls setsid() moves to a new process group and escapes
                os.killpg(). To mitigate this, we recursively discover all descendant
                PIDs via pgrep while the parent hierarchy is still intact, and send
                SIGKILL to each discovered descendant individually, in addition to
                signaling the root process group.
                """
                descendants: list[int] = []

                def _collect_descendants(p: int) -> None:
                    try:
                        res = subprocess.run(
                            ["pgrep", "-P", str(p)], capture_output=True, text=True, timeout=1.0
                        )
                        for pid_str in res.stdout.split():
                            if pid_str.isdigit():
                                child_pid = int(pid_str)
                                descendants.append(child_pid)
                                _collect_descendants(child_pid)
                    except Exception:
                        pass

                _collect_descendants(root_pid)

                for d in descendants:
                    with contextlib.suppress(Exception):
                        os.kill(d, signal.SIGKILL)  # type: ignore[attr-defined]

                with contextlib.suppress(Exception):
                    os.killpg(root_pid, signal.SIGKILL)  # type: ignore[attr-defined]

            timeout_expired = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timeout_expired = True
                _terminate_process_tree(process.pid)
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(Exception):
                        process.kill()
                    with contextlib.suppress(Exception):
                        process.wait(timeout=1.0)

            # Bound thread joins to avoid indefinite hangs if surviving or
            # detached descendants retain inherited pipe write handles.
            out_thread.join(timeout=1.0)
            err_thread.join(timeout=1.0)

            with contextlib.suppress(Exception):
                if not out_thread.is_alive() and process.stdout:
                    process.stdout.close()
            with contextlib.suppress(Exception):
                if not err_thread.is_alive() and process.stderr:
                    process.stderr.close()

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
                    stdout="",
                    stderr="Command timed out",
                    exit_code=-1,
                    command=command,
                    truncation_status={
                        "stdout": stdout_truncated[0],
                        "stderr": stderr_truncated[0],
                    },
                )

            return SandboxResult(
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode,
                command=command,
                truncation_status={"stdout": stdout_truncated[0], "stderr": stderr_truncated[0]},
            )
        except Exception as e:
            raise SandboxError(f"Failed to execute sandboxed command: {e}") from e
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)
