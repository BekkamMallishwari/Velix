import contextlib
import inspect
import os
import platform
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import SandboxError, SandboxResult


def test_sandbox_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force platform.system() to return something unsupported
    monkeypatch.setattr(platform, "system", lambda: "UnknownOS")

    manager = SandboxManager()
    assert manager.backend is None

    with pytest.raises(SandboxError, match="Sandbox backend unavailable"):
        manager.execute(["echo", "hello"], "/tmp")


def test_sandbox_capabilities() -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()
    assert caps is not None
    # We just ensure it returns a valid capability object without crashing
    assert hasattr(caps, "filesystem_isolation")


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_basic_execution(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    result = manager.execute(
        ["echo", "hello sandbox"], tmp_path, allow_network=allow_net, mode="BALANCED"
    )

    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_timeout(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"

    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    # Use _test_python to sleep
    result = manager.execute(
        [_test_python, "-c", "import time; time.sleep(5)"],
        tmp_path,
        timeout=1,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == -1
    assert "timed out" in result.stderr


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_cross_platform_workspace_restriction(tmp_path: Path) -> None:
    # Basic check that the process starts in the workspace
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"

    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    code = "import os\nprint(os.getcwd())\n"
    result = manager.execute(
        [_test_python, "-c", code], tmp_path, allow_network=allow_net, mode="BALANCED"
    )

    assert result.exit_code == 0
    # On macOS, tmp_path might be resolved to /private/var/..., check if samefile
    out_path = Path(result.stdout.strip())
    assert out_path.resolve() == tmp_path.resolve()


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_network_isolation_enforcement(tmp_path: Path) -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()

    if caps.network_isolation == "UNSUPPORTED":
        # Must fail if we demand network isolation (allow_network=False)
        with pytest.raises(
            SandboxError,
            match=(
                r"Capability '.*' is required in STRICT mode but is "
                r"(UNSUPPORTED|PARTIALLY_SUPPORTED)"
            )
        ):
            manager.execute(["echo", "hello"], tmp_path, allow_network=False)

        # Must succeed if we accept the risk (allow_network=True)
        result = manager.execute(["echo", "hello"], tmp_path, allow_network=True, mode="BALANCED")
        assert result.exit_code == 0
    else:
        # Must succeed with strict isolation (allow_network=False)
        result = manager.execute(["echo", "hello"], tmp_path, allow_network=False, mode="BALANCED")
        assert result.exit_code == 0


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_disk_limit_unsupported() -> None:
    manager = SandboxManager()
    caps = manager.get_capabilities()

    # We explicitly verify that NO backend falsely claims disk_limit support
    # since we don't have a true quota enforcement mechanism implemented.
    assert caps.disk_limit == "UNSUPPORTED"


def test_sandbox_policy_timeout_synchronization(tmp_path: Path) -> None:
    from velix_agent.sandbox.backends.base import SandboxBackend
    from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
    from velix_agent.sandbox.result import SandboxResult

    captured_policy: SandboxPolicy | None = None

    class MockBackend(SandboxBackend):
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
                disk_limit="UNSUPPORTED",
                runtime_isolation="UNSUPPORTED",
                observability="UNSUPPORTED",
                security_hardening="UNSUPPORTED",
            )

        def execute(
            self, command: list[str], policy: SandboxPolicy, timeout: int = 30
        ) -> SandboxResult:
            nonlocal captured_policy
            captured_policy = policy
            return SandboxResult(stdout="", stderr="", exit_code=0, command=command)

    manager = SandboxManager(backend=MockBackend())
    manager.execute(["echo", "hi"], tmp_path, timeout=42)

    assert captured_policy is not None
    assert captured_policy.max_execution_time == 42


def test_sandbox_policy_max_output_size_forwarding(tmp_path: Path) -> None:
    from velix_agent.sandbox.backends.base import SandboxBackend
    from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
    from velix_agent.sandbox.result import SandboxResult

    captured_policy: SandboxPolicy | None = None

    class MockBackend(SandboxBackend):
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
                disk_limit="UNSUPPORTED",
                runtime_isolation="UNSUPPORTED",
                observability="UNSUPPORTED",
                security_hardening="UNSUPPORTED",
            )

        def execute(
            self, command: list[str], policy: SandboxPolicy, timeout: int = 30
        ) -> SandboxResult:
            nonlocal captured_policy
            captured_policy = policy
            return SandboxResult(stdout="", stderr="", exit_code=0, command=command)

    manager = SandboxManager(backend=MockBackend())
    manager.execute(["echo", "hi"], tmp_path, max_output_size=1234)

    assert captured_policy is not None
    assert captured_policy.max_output_size == 1234


def test_sandbox_negative_max_output_size_rejected(tmp_path: Path) -> None:
    from velix_agent.sandbox.policy import SandboxPolicy

    # SandboxPolicy rejects negative max_output_size in __post_init__
    with pytest.raises(ValueError, match="max_output_size must be non-negative"):
        SandboxPolicy(workspace_root=tmp_path, max_output_size=-1)

    # SandboxManager rejects negative max_output_size
    manager = SandboxManager()
    with pytest.raises(SandboxError, match="max_output_size must be non-negative"):
        manager.execute(["echo", "hi"], tmp_path, max_output_size=-5)


@pytest.mark.parametrize(
    "backend_cls_name",
    [
        "MacOSSandboxBackend",
        "LinuxSandboxBackend",
        "WindowsSandboxBackend",
    ],
)
def test_backend_read_stream_output_limits(backend_cls_name: str) -> None:
    import io
    import typing

    reader_fn: typing.Callable[..., None]
    if backend_cls_name == "MacOSSandboxBackend":
        from velix_agent.sandbox.backends.macos import MacOSSandboxBackend

        reader_fn = MacOSSandboxBackend._read_stream
    elif backend_cls_name == "LinuxSandboxBackend":
        from velix_agent.sandbox.backends.linux import LinuxSandboxBackend

        reader_fn = LinuxSandboxBackend._read_stream
    else:
        from velix_agent.sandbox.backends.windows import WindowsSandboxBackend

        reader_fn = WindowsSandboxBackend._read_stream

    # 1. Normal / small limit truncation
    stream = io.BytesIO(b"0123456789" * 10)  # 100 bytes
    chunks: list[bytes] = []
    truncated = [False]
    reader_fn(stream, chunks, truncated, max_bytes=35)
    captured = b"".join(chunks)
    assert len(captured) == 35
    assert captured == (b"0123456789" * 10)[:35]
    assert truncated[0] is True
    # Stream must be drained completely
    assert stream.read() == b""

    # 2. Large limit (no truncation)
    stream = io.BytesIO(b"hello world")
    chunks = []
    truncated = [False]
    reader_fn(stream, chunks, truncated, max_bytes=1000)
    assert b"".join(chunks) == b"hello world"
    assert truncated[0] is False

    # 3. Zero limit with data emitted: no data retained, flagged as truncated
    stream = io.BytesIO(b"data emitted")
    chunks = []
    truncated = [False]
    reader_fn(stream, chunks, truncated, max_bytes=0)
    assert b"".join(chunks) == b""
    assert truncated[0] is True
    # Drained
    assert stream.read() == b""

    # 4. Zero limit with empty stream: not truncated
    stream = io.BytesIO(b"")
    chunks = []
    truncated = [False]
    reader_fn(stream, chunks, truncated, max_bytes=0)
    assert b"".join(chunks) == b""
    assert truncated[0] is False

    # 5. Continuous large data drained without unbounded chunk growth
    large_data = b"x" * 200_000
    stream = io.BytesIO(large_data)
    chunks = []
    truncated = [False]
    reader_fn(stream, chunks, truncated, max_bytes=50)
    assert len(b"".join(chunks)) == 50
    assert truncated[0] is True
    assert stream.read() == b""  # Fully drained


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_functional_small_output_limit(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    result = manager.execute(
        [_test_python, "-c", "print('A' * 500)"],
        tmp_path,
        max_output_size=50,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == 0
    assert result.truncation_status["stdout"] is True
    assert result.truncation_status["stderr"] is False
    assert "[TRUNCATED: Output exceeded maximum size limit]" in result.stdout
    raw_part = result.stdout.split(r"\n...[TRUNCATED")[0]
    assert len(raw_part.encode("utf-8")) <= 50


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_functional_large_output_limit_no_truncation(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    result = manager.execute(
        [_test_python, "-c", "print('hello' * 10)"],
        tmp_path,
        max_output_size=10_000,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == 0
    assert result.truncation_status == {"stdout": False, "stderr": False}
    assert "hello" * 10 in result.stdout
    assert "[TRUNCATED" not in result.stdout


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_functional_zero_output_limit(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    # Case A: command emits data with limit=0 -> truncated, no original data
    result = manager.execute(
        [_test_python, "-c", "print('should be truncated completely')"],
        tmp_path,
        max_output_size=0,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == 0
    assert result.truncation_status["stdout"] is True
    assert "should be truncated completely" not in result.stdout
    assert "[TRUNCATED" in result.stdout

    # Case B: command emits NO data with limit=0 -> not truncated, empty output
    result_empty = manager.execute(
        [_test_python, "-c", "pass"],
        tmp_path,
        max_output_size=0,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result_empty.exit_code == 0
    assert result_empty.truncation_status == {"stdout": False, "stderr": False}
    assert result_empty.stdout == ""
    assert result_empty.stderr == ""


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_functional_independent_stream_limits(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    code = (
        "import sys\n"
        "sys.stdout.write('O' * 200)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('E' * 15)\n"
        "sys.stderr.flush()\n"
    )
    result = manager.execute(
        [_test_python, "-c", code],
        tmp_path,
        max_output_size=50,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == 0
    assert result.truncation_status["stdout"] is True
    assert result.truncation_status["stderr"] is False
    assert "[TRUNCATED" in result.stdout
    assert "[TRUNCATED" not in result.stderr
    assert result.stderr == "E" * 15


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_functional_continuous_output_timeout_and_memory_bounded(tmp_path: Path) -> None:
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    code = (
        "import sys, time\n"
        "while True:\n"
        "    sys.stdout.write('x' * 1024)\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.01)\n"
    )
    result = manager.execute(
        [_test_python, "-c", code],
        tmp_path,
        timeout=1,
        max_output_size=100,
        allow_network=allow_net,
        mode="BALANCED",
    )

    assert result.exit_code == -1
    assert "timed out" in result.stderr.lower()
    assert result.truncation_status["stdout"] is True


def test_sandbox_cpu_limit_defaults_are_false(tmp_path: Path) -> None:
    """Verify that SandboxPolicy and SandboxManager.execute default cpu_limit to False."""
    # 1. SandboxPolicy default
    policy = SandboxPolicy(workspace_root=tmp_path)
    assert policy.cpu_limit is False

    # 2. SandboxManager.execute parameter default
    sig = inspect.signature(SandboxManager.execute)
    assert "cpu_limit" in sig.parameters
    assert sig.parameters["cpu_limit"].default is False

    # 3. Default execution forwards cpu_limit=False to the backend
    manager = SandboxManager()
    if manager.backend is not None:
        mock_backend = MagicMock()
        mock_backend.get_capabilities.return_value = manager.backend.get_capabilities()
        mock_backend.execute.return_value = SandboxResult(
            stdout="", stderr="", exit_code=0, command=["echo"]
        )
        manager.backend = mock_backend

        manager.execute(["echo", "hi"], tmp_path, mode="BALANCED")
        assert mock_backend.execute.called
        call_policy = mock_backend.execute.call_args[0][1]
        assert call_policy.cpu_limit is False


def test_sandbox_explicit_cpu_limit_strict_mode_rejection(tmp_path: Path) -> None:
    """Verify explicit cpu_limit=True fails closed in strict mode for non-SUPPORTED backends."""
    manager = SandboxManager()

    from velix_agent.sandbox.policy import SupportStatus

    unsupported_statuses: list[SupportStatus] = [
        "PARTIALLY_SUPPORTED",
        "UNSUPPORTED",
        "NOT_AVAILABLE",
    ]
    for status in unsupported_statuses:
        test_caps = SandboxCapabilities(
            filesystem_isolation="SUPPORTED",
            network_isolation="SUPPORTED",
            cpu_limit=status,
            memory_limit="SUPPORTED",
            process_limit="SUPPORTED",
            timeout="SUPPORTED",
            output_limit="SUPPORTED",
            secret_filtering="SUPPORTED",
            disk_limit="SUPPORTED",
            runtime_isolation="SUPPORTED",
            observability="SUPPORTED",
            security_hardening="SUPPORTED",
        )
        mock_backend = MagicMock()
        mock_backend.get_capabilities.return_value = test_caps
        mock_backend.execute.return_value = SandboxResult(
            stdout="", stderr="", exit_code=0, command=["echo"]
        )
        manager.backend = mock_backend

        # Explicit cpu_limit=True in STRICT mode MUST fail closed
        with pytest.raises(
            SandboxError,
            match=rf"Capability 'cpu_limit' is required in STRICT mode but is (only )?{status}\.",
        ):
            manager.execute(["echo", "test"], tmp_path, mode="STRICT", cpu_limit=True)

        # In contrast, default execution (cpu_limit=False) does not require cpu_limit and succeeds
        res_default = manager.execute(["echo", "test"], tmp_path, mode="STRICT")
        assert res_default.exit_code == 0

        # Explicit cpu_limit=False in STRICT mode also succeeds
        res_explicit_false = manager.execute(
            ["echo", "test"], tmp_path, mode="STRICT", cpu_limit=False
        )
        assert res_explicit_false.exit_code == 0


def test_sandbox_explicit_cpu_limit_balanced_mode_tolerates_partial(tmp_path: Path) -> None:
    """Verify cpu_limit=True does not raise in BALANCED mode when partially supported."""
    manager = SandboxManager()
    test_caps = SandboxCapabilities(
        filesystem_isolation="SUPPORTED",
        network_isolation="SUPPORTED",
        cpu_limit="PARTIALLY_SUPPORTED",
        memory_limit="SUPPORTED",
        process_limit="SUPPORTED",
        timeout="SUPPORTED",
        output_limit="SUPPORTED",
        secret_filtering="SUPPORTED",
        disk_limit="SUPPORTED",
        runtime_isolation="SUPPORTED",
        observability="SUPPORTED",
        security_hardening="SUPPORTED",
    )
    mock_backend = MagicMock()
    mock_backend.get_capabilities.return_value = test_caps
    mock_backend.execute.return_value = SandboxResult(
        stdout="", stderr="", exit_code=0, command=["echo"]
    )
    manager.backend = mock_backend

    res = manager.execute(["echo", "test"], tmp_path, mode="BALANCED", cpu_limit=True)
    assert res.exit_code == 0
    assert mock_backend.execute.called


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_timeout_with_detached_descendant(tmp_path: Path) -> None:
    """Verify timeout handling returns boundedly even if a descendant detaches and survives."""
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    pid_file = tmp_path / "descendant.pid"
    code = (
        "import sys, time, os, subprocess\n"
        f"pid_file = {str(pid_file)!r}\n"
        "if hasattr(os, 'fork') and hasattr(os, 'setsid'):\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        os.setsid()\n"
        "        with open(pid_file, 'w') as f:\n"
        "            f.write(str(os.getpid()))\n"
        "        time.sleep(10)\n"
        "        sys.exit(0)\n"
        "else:\n"
        "    sub = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "    with open(pid_file, 'w') as f:\n"
        "        f.write(str(sub.pid))\n"
        "time.sleep(10)\n"
        "sys.exit(0)\n"
    )

    t0 = time.time()
    try:
        result = manager.execute(
            [_test_python, "-c", code],
            tmp_path,
            timeout=1,
            allow_network=allow_net,
            mode="BALANCED",
        )
        elapsed = time.time() - t0
        assert result.exit_code == -1
        assert "timed out" in result.stderr
        # Must return in bounded time (~1-3s), not hang waiting for 10s sleeper
        assert elapsed < 5.0
    finally:
        if pid_file.exists():
            try:
                desc_pid = int(pid_file.read_text().strip())
                if platform.system() == "Windows":
                    import ctypes

                    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                    handle = kernel32.OpenProcess(1, False, desc_pid)
                    if handle:
                        kernel32.TerminateProcess(handle, 1)
                        kernel32.CloseHandle(handle)
                elif platform.system() == "Darwin" and desc_pid > 1:
                    import signal

                    os.kill(desc_pid, signal.SIGKILL)
            except Exception:
                pass
            with contextlib.suppress(OSError):
                pid_file.unlink()


@pytest.mark.skipif(
    platform.system() not in ("Darwin", "Linux", "Windows"), reason="Unsupported OS"
)
def test_sandbox_normal_root_exit_with_background_descendant(tmp_path: Path) -> None:
    """Verify normal root exit returns boundedly and captures output when descendant survives."""
    manager = SandboxManager()
    allow_net = manager.get_capabilities().network_isolation == "UNSUPPORTED"
    _test_python = "python3" if platform.system() == "Linux" else sys.executable

    pid_file = tmp_path / "descendant_normal.pid"
    code = (
        "import sys, time, os, subprocess\n"
        f"pid_file = {str(pid_file)!r}\n"
        "if hasattr(os, 'fork') and hasattr(os, 'setsid'):\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        os.setsid()\n"
        "        with open(pid_file, 'w') as f:\n"
        "            f.write(str(os.getpid()))\n"
        "        time.sleep(10)\n"
        "        sys.exit(0)\n"
        "else:\n"
        "    sub = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "    with open(pid_file, 'w') as f:\n"
        "        f.write(str(sub.pid))\n"
        "sys.stdout.write('root finished\\n')\n"
        "sys.stdout.flush()\n"
        "sys.exit(0)\n"
    )

    t0 = time.time()
    try:
        result = manager.execute(
            [_test_python, "-c", code],
            tmp_path,
            timeout=5,
            allow_network=allow_net,
            mode="BALANCED",
        )
        elapsed = time.time() - t0
        assert result.exit_code == 0
        assert "root finished" in result.stdout
        # Must return in bounded time (~1-3s), not hang waiting for 10s sleeper
        assert elapsed < 5.0
    finally:
        if pid_file.exists():
            try:
                desc_pid = int(pid_file.read_text().strip())
                if platform.system() == "Windows":
                    import ctypes

                    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                    handle = kernel32.OpenProcess(1, False, desc_pid)
                    if handle:
                        kernel32.TerminateProcess(handle, 1)
                        kernel32.CloseHandle(handle)
                elif platform.system() == "Darwin" and desc_pid > 1:
                    import signal

                    os.kill(desc_pid, signal.SIGKILL)
            except Exception:
                pass
            with contextlib.suppress(OSError):
                pid_file.unlink()
