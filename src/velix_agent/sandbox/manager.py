import contextlib
import os
import platform
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from velix_agent.sandbox.policy import SandboxCapabilities

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult

logger = get_logger("sandbox.manager")


class SandboxManager:
    """Manages platform-specific sandbox execution.

    Supported platforms:
      - macOS (Darwin): Apple Seatbelt (sandbox-exec) backend
      - Linux: Bubblewrap (bwrap) backend
      - Windows: Win32 Job Object backend

    Other platforms are unsupported and fail closed with SandboxError.
    """

    backend: SandboxBackend | None

    def __init__(self, backend: SandboxBackend | None = None, _force_none: bool = False):
        if _force_none:
            self.backend = None
        elif backend is None:
            sys_name = platform.system()
            if sys_name == "Darwin":
                from velix_agent.sandbox.backends.macos import MacOSSandboxBackend

                self.backend = MacOSSandboxBackend()
            elif sys_name == "Linux":
                from velix_agent.sandbox.backends.linux import LinuxSandboxBackend

                self.backend = LinuxSandboxBackend()
            elif sys_name == "Windows":
                from velix_agent.sandbox.backends.windows import WindowsSandboxBackend

                self.backend = WindowsSandboxBackend()
            else:
                self.backend = None
        else:
            self.backend = backend

    def get_capabilities(self) -> "SandboxCapabilities":
        from velix_agent.sandbox.policy import SandboxCapabilities

        if self.backend is None:
            return SandboxCapabilities(
                filesystem_isolation="NOT_AVAILABLE",
                network_isolation="NOT_AVAILABLE",
                cpu_limit="NOT_AVAILABLE",
                memory_limit="NOT_AVAILABLE",
                process_limit="NOT_AVAILABLE",
                timeout="NOT_AVAILABLE",
                output_limit="NOT_AVAILABLE",
                secret_filtering="NOT_AVAILABLE",
                disk_limit="NOT_AVAILABLE",
                runtime_isolation="NOT_AVAILABLE",
                observability="NOT_AVAILABLE",
                security_hardening="NOT_AVAILABLE",
            )
        return self.backend.get_capabilities()

    def _validate_capabilities(self, policy: SandboxPolicy) -> None:
        caps = self.get_capabilities()

        # Determine what is required to be supported
        # In STRICT: core isolation is unconditionally required. Requested limits are required.
        # In BALANCED/DEVELOPMENT: only timeout and output_limit are unconditionally required.
        # However, ANY policy flag requested by the caller (like cpu_limit=True) MUST be supported
        # if the policy requires it to be strictly enforced.

        required_caps: list[str] = ["timeout", "output_limit"]

        if policy.mode.name == "STRICT":
            required_caps.extend(["filesystem_isolation", "secret_filtering"])
            if not policy.allow_network:
                required_caps.append("network_isolation")
            if policy.cpu_limit:
                required_caps.append("cpu_limit")
            if policy.memory_limit is not None:
                required_caps.append("memory_limit")
            if policy.process_limit is not None:
                required_caps.append("process_limit")
        elif policy.mode.name == "BALANCED" or policy.mode.name == "DEVELOPMENT":
            if not policy.allow_network:
                required_caps.append("network_isolation")

        for cap_name in required_caps:
            status = getattr(caps, cap_name)
            if status in ("UNSUPPORTED", "NOT_AVAILABLE"):
                raise SandboxError(
                    f"Capability '{cap_name}' is required in {policy.mode.name} "
                    f"mode but is {status}."
                )
            if status == "PARTIALLY_SUPPORTED" and policy.mode.name == "STRICT":
                raise SandboxError(
                    f"Capability '{cap_name}' is required in STRICT "
                    f"mode but is only PARTIALLY_SUPPORTED."
                )

        if policy.mode.name != "STRICT":
            if caps.filesystem_isolation == "UNSUPPORTED":
                sys_name = platform.system()
                logger.warning(
                    f"Filesystem isolation is UNSUPPORTED on {sys_name} "
                    f"in {policy.mode.name} mode. "
                    "Filesystem access is not confined to workspace_root "
                    f"'{policy.workspace_root}'. "
                    "Commands may access any files permitted to the host user."
                )

            # Warn on any requested capability that is only partially supported
            requested_caps = ["timeout", "output_limit"]
            if not policy.allow_network:
                requested_caps.append("network_isolation")
            if policy.cpu_limit:
                requested_caps.append("cpu_limit")
            if policy.memory_limit is not None:
                requested_caps.append("memory_limit")
            if policy.process_limit is not None:
                requested_caps.append("process_limit")
            if policy.secret_filtering:
                requested_caps.append("secret_filtering")

            for cap_name in requested_caps:
                if getattr(caps, cap_name) == "PARTIALLY_SUPPORTED":
                    from velix_agent.core.logging import get_logger

                    get_logger("sandbox.manager").warning(
                        f"Capability '{cap_name}' is only PARTIALLY_SUPPORTED."
                    )

    @staticmethod
    def _is_filesystem_root(path: Path | str) -> bool:
        """Check if path is a filesystem root (POSIX root, Windows drive root, or UNC root)."""
        raw_str = str(path).strip()
        if re.match(r"^[a-zA-Z]:[\\/]*$", raw_str):
            return True
        if re.match(r"^\\\\[^\\]+\\[^\\]+[\\/]*$", raw_str):
            return True
        if raw_str in ("/", "\\"):
            return True

        p = Path(path)
        if p.is_absolute() and p.parent == p:
            return True
        if p.anchor and p == Path(p.anchor):
            return True

        resolved = p.resolve()
        if resolved.parent == resolved:
            return True
        if resolved.anchor and resolved == Path(resolved.anchor):
            return True
        res_str = str(resolved).rstrip("\\/")
        anc_str = resolved.anchor.rstrip("\\/")
        return bool(anc_str and res_str.lower() == anc_str.lower())

    @staticmethod
    def _is_home_directory(path: Path | str) -> bool:
        """Check if path refers to the current user's home directory."""
        p = Path(path).resolve()

        home_candidates: list[Path] = []
        with contextlib.suppress(Exception):
            home_candidates.append(Path.home().resolve())
        if os.environ.get("HOME"):
            with contextlib.suppress(Exception):
                home_candidates.append(Path(os.environ["HOME"]).resolve())
        if os.environ.get("USERPROFILE"):
            with contextlib.suppress(Exception):
                home_candidates.append(Path(os.environ["USERPROFILE"]).resolve())

        for home in home_candidates:
            if p == home:
                return True
            # Case-insensitive comparison for Windows and case-insensitive/preserving filesystems
            norm_p = str(p).replace("/", "\\").lower()
            norm_home = str(home).replace("/", "\\").lower()
            if norm_p == norm_home:
                return True
            with contextlib.suppress(OSError, ValueError):
                if p.exists() and home.exists() and os.path.samefile(p, home):
                    return True

        return False

    def _validate_workspace_root(self, workspace_root: str | Path) -> Path:
        """Validate that workspace_root is an existing directory and not a dangerous root."""
        raw_path = Path(workspace_root)
        if self._is_filesystem_root(workspace_root) or self._is_filesystem_root(raw_path):
            raise SandboxError(
                f"Invalid workspace root '{workspace_root}': filesystem root is not allowed"
            )

        root = raw_path.expanduser().resolve()
        if self._is_filesystem_root(root):
            raise SandboxError(
                f"Invalid workspace root '{workspace_root}': filesystem root is not allowed"
            )

        if not root.is_dir():
            raise SandboxError(f"Invalid workspace root: {root}")

        if self._is_home_directory(root) or self._is_home_directory(workspace_root):
            raise SandboxError(
                f"Invalid workspace root '{workspace_root}': user home directory is not allowed"
            )

        return root

    def execute(
        self,
        command: list[str],
        workspace_root: str | Path,
        timeout: int = 30,
        allow_network: bool = False,
        mode: str = "STRICT",
        secrets: dict[str, str] | None = None,
        memory_limit: int | None = None,
        process_limit: int | None = None,
        cpu_limit: bool = False,
        max_output_size: int = 50_000,
    ) -> SandboxResult:
        """Execute a command in the sandbox.

        Args:
            command: The command to execute.
            workspace_root: The root directory for the sandbox workspace.
            timeout: Maximum execution time in seconds.
            allow_network: Whether to allow outbound network access.
            mode: Sandbox policy mode ('STRICT', 'BALANCED', 'DEVELOPMENT').
            secrets: Dictionary of secrets to inject and redact.
            memory_limit: Maximum memory in bytes.
            process_limit: Maximum number of processes.
            cpu_limit: Whether to enforce CPU time limits (requires SUPPORTED in STRICT mode).
            max_output_size: Maximum raw bytes captured from each of stdout and stderr.
                When a stream exceeds this limit, capture stops at this byte boundary,
                the stream's truncation_status is flagged True, and OUTPUT_TRUNCATION_MARKER
                is appended to the returned string.
        """
        if max_output_size < 0:
            raise SandboxError(f"max_output_size must be non-negative, got {max_output_size}")

        if self.backend is None:
            sys_name = platform.system()
            raise SandboxError(f"Sandbox backend unavailable for platform: {sys_name}")

        root = self._validate_workspace_root(workspace_root)

        from velix_agent.sandbox.policy import SandboxPolicyMode
        from velix_agent.sandbox.secrets import SecretStore

        policy_mode = SandboxPolicyMode[mode]
        policy = SandboxPolicy(
            workspace_root=root,
            mode=policy_mode,
            allow_network=allow_network,
            max_execution_time=timeout,
            max_output_size=max_output_size,
            secrets=list(secrets.keys()) if secrets else [],
            memory_limit=memory_limit,
            process_limit=process_limit,
            cpu_limit=cpu_limit,
        )

        self._validate_capabilities(policy)

        # Build injected environment using a strictly per-execution SecretStore
        local_store = SecretStore()
        if secrets:
            for k, v in secrets.items():
                local_store.register(k, v)
            policy.env = local_store.create_environment(policy.secrets)

        # Generate execution ID
        import time
        import uuid

        execution_id = str(uuid.uuid4())

        # We need to capture backend name for observability
        backend_name = self.backend.__class__.__name__

        start_time = time.monotonic()
        try:
            result = self.backend.execute(command, policy, timeout=timeout)
            duration = time.monotonic() - start_time

            result.execution_id = execution_id
            result.backend = backend_name
            result.duration = duration

            caps = self.get_capabilities()
            if policy.mode.name != "STRICT" and caps.filesystem_isolation == "UNSUPPORTED":
                result.security_events.append(
                    "UNISOLATED_FILESYSTEM: "
                    f"Filesystem isolation is UNSUPPORTED on {platform.system()} "
                    f"in {policy.mode.name} mode. "
                    "Filesystem access is not confined to workspace_root "
                    f"'{policy.workspace_root}'. "
                    "Commands may access any files permitted to the host user."
                )

            if policy.secret_filtering:
                stdout_truncated = result.truncation_status.get("stdout", False)
                stderr_truncated = result.truncation_status.get("stderr", False)
                result.stdout = local_store.redact(result.stdout, truncated=stdout_truncated)
                result.stderr = local_store.redact(result.stderr, truncated=stderr_truncated)
                result.command = [local_store.redact(c) for c in result.command]

            return result
        finally:
            local_store.cleanup()
