import platform
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from velix_agent.sandbox.policy import SandboxCapabilities

from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult


class SandboxManager:
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

    def execute(
        self,
        command: list[str],
        workspace_root: str | Path,
        timeout: int = 30,
        allow_network: bool = False,
        mode: str = "STRICT",
        secrets: dict[str, str] | None = None,
    ) -> SandboxResult:
        if self.backend is None:
            raise SandboxError(f"Sandbox backend unavailable for platform: {platform.system()}")

        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise SandboxError(f"Invalid workspace root: {root}")

        from velix_agent.sandbox.policy import SandboxPolicyMode
        from velix_agent.sandbox.secrets import SecretStore

        policy_mode = SandboxPolicyMode[mode]
        policy = SandboxPolicy(
            workspace_root=root,
            mode=policy_mode,
            allow_network=allow_network,
            secrets=list(secrets.keys()) if secrets else [],
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

            if policy.secret_filtering:
                result.stdout = local_store.redact(result.stdout)
                result.stderr = local_store.redact(result.stderr)
                result.command = [local_store.redact(c) for c in result.command]

            return result
        finally:
            local_store.cleanup()
