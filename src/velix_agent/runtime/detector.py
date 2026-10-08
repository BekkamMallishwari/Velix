import shutil
from pathlib import Path

from velix_agent.runtime.models import RuntimeInfo, RuntimeStatus
from velix_agent.sandbox.manager import SandboxManager


class RuntimeDetector:
    def __init__(self, sandbox_manager: SandboxManager | None = None):
        self.sandbox = sandbox_manager or SandboxManager()

    def _run_version_cmd(
        self, executable: str, cmd_args: list[str], workspace_root: Path
    ) -> str | None:
        """Safely run a version command using the sandbox."""
        try:
            # We don't want strict isolation for host detection if we need to run system binaries
            # But we must prevent unbounded output and timeouts
            res = self.sandbox.execute(
                command=[executable, *cmd_args],
                workspace_root=workspace_root,
                timeout=5,
                mode="DEVELOPMENT",  # Use DEVELOPMENT to allow reading system binaries easily
            )
            if res.exit_code == 0:
                out = res.stdout.strip()
                if not out and res.stderr:
                    out = res.stderr.strip()
                # take first line
                return out.split("\n")[0]
            elif res.exit_code != -1:
                out = res.stderr.strip() or res.stdout.strip()
                if out:
                    return out.split("\n")[0]
        except Exception:
            pass
        return None

    def detect_python(self, workspace_root: Path) -> RuntimeInfo:
        # Check for virtual environment first
        venv_exec = None
        is_venv = False

        for venv_dir in [".venv", "venv"]:
            venv_path = workspace_root / venv_dir
            if venv_path.is_dir():
                win_exec = venv_path / "Scripts" / "python.exe"
                posix_exec = venv_path / "bin" / "python"
                if win_exec.exists():
                    venv_exec = str(win_exec)
                    is_venv = True
                    break
                elif posix_exec.exists():
                    venv_exec = str(posix_exec)
                    is_venv = True
                    break

        executable = venv_exec or shutil.which("python3") or shutil.which("python")

        if not executable:
            return RuntimeInfo(name="Python", status=RuntimeStatus.UNAVAILABLE)

        version = self._run_version_cmd(executable, ["--version"], workspace_root)

        # Package manager
        pm_exec = None
        pm_name = None
        if is_venv:
            venv_base = Path(executable).parent
            win_pip = venv_base / "pip.exe"
            posix_pip = venv_base / "pip"
            if win_pip.exists():
                pm_exec = str(win_pip)
            elif posix_pip.exists():
                pm_exec = str(posix_pip)
        else:
            pm_exec = shutil.which("pip3") or shutil.which("pip")

        if pm_exec:
            pm_name = "pip3" if "pip3" in pm_exec else "pip"

        return RuntimeInfo(
            name="Python",
            status=RuntimeStatus.SUPPORTED,
            executable=executable,
            version=version,
            package_manager=pm_name,
            package_manager_executable=pm_exec,
            platform="cross-platform",
            is_virtual_env=is_venv,
        )

    def detect_node(self, workspace_root: Path) -> RuntimeInfo:
        executable = shutil.which("node")
        if not executable:
            return RuntimeInfo(name="Node.js", status=RuntimeStatus.UNAVAILABLE)

        version = self._run_version_cmd(executable, ["--version"], workspace_root)

        pm_exec = shutil.which("npm")
        pm_name = "npm" if pm_exec else None

        return RuntimeInfo(
            name="Node.js",
            status=RuntimeStatus.SUPPORTED,
            executable=executable,
            version=version,
            package_manager=pm_name,
            package_manager_executable=pm_exec,
            platform="cross-platform",
        )

    def detect_java(self, workspace_root: Path) -> RuntimeInfo:
        executable = shutil.which("java")
        if not executable:
            return RuntimeInfo(name="Java", status=RuntimeStatus.UNAVAILABLE)

        version = self._run_version_cmd(executable, ["-version"], workspace_root)

        return RuntimeInfo(
            name="Java",
            status=RuntimeStatus.SUPPORTED,
            executable=executable,
            version=version,
            package_manager=None,
            package_manager_executable=None,
            platform="cross-platform",
        )

    def detect_go(self, workspace_root: Path) -> RuntimeInfo:
        executable = shutil.which("go")
        if not executable:
            return RuntimeInfo(name="Go", status=RuntimeStatus.UNAVAILABLE)

        version = self._run_version_cmd(executable, ["version"], workspace_root)

        return RuntimeInfo(
            name="Go",
            status=RuntimeStatus.SUPPORTED,
            executable=executable,
            version=version,
            package_manager="go",
            package_manager_executable=executable,
            platform="cross-platform",
        )

    def detect_rust(self, workspace_root: Path) -> RuntimeInfo:
        executable = shutil.which("rustc")
        if not executable:
            return RuntimeInfo(name="Rust", status=RuntimeStatus.UNAVAILABLE)

        version = self._run_version_cmd(executable, ["--version"], workspace_root)

        pm_exec = shutil.which("cargo")
        pm_name = "cargo" if pm_exec else None

        return RuntimeInfo(
            name="Rust",
            status=RuntimeStatus.SUPPORTED,
            executable=executable,
            version=version,
            package_manager=pm_name,
            package_manager_executable=pm_exec,
            platform="cross-platform",
        )
