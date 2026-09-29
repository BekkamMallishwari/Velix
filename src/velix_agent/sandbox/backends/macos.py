import os
import subprocess
import tempfile

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult

logger = get_logger("sandbox.macos")


class MacOSSandboxBackend(SandboxBackend):
    def _generate_profile(self, policy: SandboxPolicy) -> str:
        home = os.environ.get("HOME", "/tmp")
        profile = [
            "(version 1)",
            '(import "system.sb")',
            "(allow process-exec)",
            "(allow process-fork)",
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
        profile.append(')')

        workspace_path = policy.workspace_root.resolve().as_posix()
        profile.append(f'(allow file-read* file-write* (subpath "{workspace_path}"))')
        profile.append(f'(deny file-write* (subpath "{workspace_path}/.git"))')

        if not policy.allow_network:
            profile.append("(deny network*)")

        return "\n".join(profile)

    def execute(self, command: list[str], policy: SandboxPolicy) -> SandboxResult:
        import platform

        if platform.system() != "Darwin":
            raise SandboxError("MacOSSandboxBackend is only available on macOS.")

        profile_content = self._generate_profile(policy)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sb", delete=False) as f:
            f.write(profile_content)
            profile_path = f.name

        try:
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
                "HOME": os.environ.get("HOME", "/tmp"),
                "USER": os.environ.get("USER", "nobody"),
            }

            sandbox_cmd = ["sandbox-exec", "-f", profile_path, *command]

            logger.info(f"Executing sandboxed command: {' '.join(command)}")
            result = subprocess.run(
                sandbox_cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=policy.workspace_root.as_posix(),
                timeout=30,
            )

            return SandboxResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                command=command,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                stdout="", stderr="Command timed out", exit_code=-1, command=command
            )
        except Exception as e:
            raise SandboxError(f"Failed to execute sandboxed command: {e}") from e
        finally:
            if os.path.exists(profile_path):
                os.remove(profile_path)
