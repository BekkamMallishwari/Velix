import ctypes
import os
import platform
import subprocess
import threading
import typing

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult

logger = get_logger("sandbox.windows")

if platform.system() == "Windows":
    from ctypes import wintypes

    # Define Win32 API structs and constants
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(wintypes.ULONG)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # Constants
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x0200

    JobObjectExtendedLimitInformation = 9
    CREATE_SUSPENDED = 0x00000004

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    ntdll = ctypes.windll.ntdll  # type: ignore[attr-defined]

    CreateJobObjectW = kernel32.CreateJobObjectW
    CreateJobObjectW.restype = wintypes.HANDLE
    CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]

    SetInformationJobObject = kernel32.SetInformationJobObject
    SetInformationJobObject.restype = wintypes.BOOL
    SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]

    AssignProcessToJobObject = kernel32.AssignProcessToJobObject
    AssignProcessToJobObject.restype = wintypes.BOOL
    AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    TerminateJobObject = kernel32.TerminateJobObject
    TerminateJobObject.restype = wintypes.BOOL
    TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]

    CloseHandle = kernel32.CloseHandle
    CloseHandle.restype = wintypes.BOOL
    CloseHandle.argtypes = [wintypes.HANDLE]

    NtResumeProcess = ntdll.NtResumeProcess
    NtResumeProcess.restype = ctypes.c_long
    NtResumeProcess.argtypes = [wintypes.HANDLE]


class WindowsSandboxBackend(SandboxBackend):
    """
    Tier 1 Native Windows Job Object Backend.
    Uses Win32 Job Objects to enforce resource limits and cleanup process trees.
    Does NOT provide filesystem or network isolation.
    Requires NO Administrator privileges.
    """

    MAX_OUTPUT_BYTES = 50_000

    @classmethod
    def get_capabilities(cls) -> SandboxCapabilities:
        return SandboxCapabilities(
            filesystem_isolation="UNSUPPORTED",
            network_isolation="UNSUPPORTED",
            cpu_limit="UNSUPPORTED",  # CPU rate control is complex, relying on timeout
            memory_limit="SUPPORTED",
            process_limit="SUPPORTED",
            timeout="SUPPORTED",
            output_limit="SUPPORTED",
            secret_filtering="SUPPORTED",
            disk_limit="UNSUPPORTED",
            runtime_isolation="UNSUPPORTED",
            observability="UNSUPPORTED",
            security_hardening="UNSUPPORTED",
        )

    @staticmethod
    def _read_stream(
        stream: typing.IO[bytes], chunks_list: list[bytes], truncated_flag: list[bool]
    ) -> None:
        total_bytes = 0
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break

            if total_bytes < WindowsSandboxBackend.MAX_OUTPUT_BYTES:
                remaining = WindowsSandboxBackend.MAX_OUTPUT_BYTES - total_bytes
                chunks_list.append(chunk[:remaining])
                total_bytes += len(chunk)
                if len(chunk) > remaining:
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True

    def execute(
        self, command: list[str], policy: SandboxPolicy, timeout: int = 30
    ) -> SandboxResult:
        if platform.system() != "Windows":
            raise SandboxError("WindowsSandboxBackend is only available on Windows.")

        if not policy.allow_network:
            raise SandboxError("Network isolation is unavailable on Windows Tier 1.")

        workspace_path = policy.workspace_root.resolve().as_posix()

        job = CreateJobObjectW(None, None)
        if not job:
            raise SandboxError(
                f"Failed to create Job Object. Error: {ctypes.GetLastError()}"  # type: ignore[attr-defined]
            )

        try:
            limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

            if policy.process_limit:
                limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                limits.BasicLimitInformation.ActiveProcessLimit = policy.process_limit

            if policy.memory_limit:
                limits.BasicLimitInformation.LimitFlags |= (
                    JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
                )
                limits.ProcessMemoryLimit = policy.memory_limit
                limits.JobMemoryLimit = policy.memory_limit

            result = SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            )
            if not result:
                raise SandboxError(
                    f"Failed to set Job Object limits. Error: {ctypes.GetLastError()}"  # type: ignore[attr-defined]
                )

            allowed_env = [
                "PATH",
                "SystemRoot",
                "USERPROFILE",
                "ALLUSERSPROFILE",
                "SystemDrive",
                "ProgramData",
                "ProgramFiles",
                "ProgramFiles(x86)",
            ]
            env = {k: os.environ.get(k, "") for k in allowed_env if k in os.environ}
            env["TEMP"] = os.environ.get("TEMP", "")
            env["TMP"] = os.environ.get("TMP", "")
            env.update(policy.env)

            logger.info(f"Executing sandboxed command: {' '.join(command)}")

            # Start process suspended to prevent escape races
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=workspace_path,
                creationflags=CREATE_SUSPENDED,
            )

            process_handle = int(getattr(process, "_handle", 0))

            # Assign immediately to the job.
            if not AssignProcessToJobObject(job, process_handle):
                # Critical cleanup if assignment fails
                process.kill()
                process.wait()
                raise SandboxError(
                    f"Failed to assign process to Job Object. Error: {ctypes.GetLastError()}"  # type: ignore[attr-defined]
                )

            # Job assignment succeeded, resume process
            status = NtResumeProcess(process_handle)
            if status != 0:
                process.kill()
                process.wait()
                raise SandboxError(f"Failed to resume suspended process. NTSTATUS: {status}")

            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_truncated = [False]
            stderr_truncated = [False]

            out_thread = threading.Thread(
                target=self._read_stream, args=(process.stdout, stdout_chunks, stdout_truncated)
            )
            err_thread = threading.Thread(
                target=self._read_stream, args=(process.stderr, stderr_chunks, stderr_truncated)
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

            # If timeout, TerminateJobObject guarantees the tree is cleaned up
            if timeout_expired:
                TerminateJobObject(job, 1)
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
            CloseHandle(job)
