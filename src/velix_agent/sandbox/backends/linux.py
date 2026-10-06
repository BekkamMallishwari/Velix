import contextlib
import os
import platform
import resource
import shutil
import signal
import subprocess
import threading
import typing

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult

logger = get_logger("sandbox.linux")


class LinuxSandboxBackend(SandboxBackend):
    MAX_OUTPUT_BYTES = 50_000

    @classmethod
    def get_capabilities(cls) -> SandboxCapabilities:
        return SandboxCapabilities(
            filesystem_isolation="SUPPORTED",
            network_isolation="SUPPORTED",
            cpu_limit="SUPPORTED",
            memory_limit="SUPPORTED",
            process_limit="SUPPORTED",
            timeout="SUPPORTED",
            output_limit="SUPPORTED",
            secret_filtering="SUPPORTED",
        )

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

            if total_bytes < LinuxSandboxBackend.MAX_OUTPUT_BYTES:
                remaining = LinuxSandboxBackend.MAX_OUTPUT_BYTES - total_bytes
                chunks_list.append(chunk[:remaining])
                total_bytes += len(chunk)
                if len(chunk) > remaining:
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True

    def execute(
        self, command: list[str], policy: SandboxPolicy, timeout: int = 30
    ) -> SandboxResult:
        if platform.system() != "Linux":
            raise SandboxError("LinuxSandboxBackend is only available on Linux.")

        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            raise SandboxError(
                "Secure Linux sandbox backend unavailable. "
                "Bubblewrap (bwrap) is required for namespace isolation."
            )

        workspace_path = policy.workspace_root.resolve().as_posix()

        bwrap_cmd = [
            bwrap_path,
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/alternatives", "/etc/alternatives",
            "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind", "/etc/ssl", "/etc/ssl",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--bind", workspace_path, workspace_path,
        ]

        if not policy.allow_network:
            bwrap_cmd.append("--unshare-net")

        bwrap_cmd.extend(["--", *command])

        def set_limits() -> None:
            # Enforce CPU limit
            if policy.cpu_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))

            # Memory Limit
            if policy.memory_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(
                        resource.RLIMIT_AS, (policy.memory_limit, policy.memory_limit)
                    )

            # Process Limit
            if policy.process_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(
                        resource.RLIMIT_NPROC, (policy.process_limit, policy.process_limit)
                    )

        try:
            # Environment filtering
            allowed_env = ["PATH", "HOME", "USER", "LANG", "LC_ALL"]
            env = {k: os.environ.get(k, "") for k in allowed_env if k in os.environ}
            # Explicity set TMPDIR to /tmp which is a tmpfs in bwrap
            env["TMPDIR"] = "/tmp"

            logger.info(f"Executing sandboxed command: {' '.join(command)}")

            process = subprocess.Popen(
                bwrap_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=workspace_path,
                start_new_session=True,
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
