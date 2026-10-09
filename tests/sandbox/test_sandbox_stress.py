"""
Bounded sandbox resource stress-test scaffolding.

Safety contract:
    - All tests carry a 30-second hard outer timeout guard.
    - Memory allocations inside the sandbox are capped at 128 MiB.
    - At most MAX_CHILD_PROCESSES=50 child processes are ever attempted.
    - No unbounded fork-bomb or disk-exhaustion loops.
    - Tests skip gracefully if the required capability is not SUPPORTED on the
      current platform; a skip is NEVER treated as evidence of support.

Windows limitations (documented):
    - filesystem_isolation and network_isolation are UNSUPPORTED on Windows.
    - No stress test in this file asserts those protections on Windows.
"""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

import pytest

from velix_agent.sandbox.manager import SandboxManager

_SYSTEM = platform.system()

# Safety constants — never exceed these in any test
_OUTER_TIMEOUT_SEC = 30
_MAX_CHILD_PROCESSES = 50
_MEMORY_CAP_BYTES = 128 * 1024 * 1024  # 128 MiB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _caps() -> object:
    return SandboxManager().get_capabilities()


def _has_timeout(caps: object) -> bool:
    return getattr(caps, "timeout", "NOT_AVAILABLE") == "SUPPORTED"


def _has_fs_isolation(caps: object) -> bool:
    return getattr(caps, "filesystem_isolation", "NOT_AVAILABLE") == "SUPPORTED"


def _has_output_limit(caps: object) -> bool:
    return getattr(caps, "output_limit", "NOT_AVAILABLE") == "SUPPORTED"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def caps() -> object:
    return _caps()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "stress_workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def manager() -> SandboxManager:
    return SandboxManager()


# ---------------------------------------------------------------------------
# Stress: timeout enforcement under load
# ---------------------------------------------------------------------------


@pytest.mark.timeout(35)
def test_stress_timeout_under_cpu_load(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """A CPU-bound infinite loop must be killed within the timeout budget.

    Acceptable exit codes:
      -1       Our timeout handler fired first (process.wait(timeout=N) expired)
      -24      SIGXCPU fired first because macOS RLIMIT_CPU == sandbox_timeout
      -9       SIGKILL from killpg fired before SIGXCPU was delivered
      >0       bwrap/sandbox-exec wrapper exited with a non-zero code

    The exact signal depends on a race between RLIMIT_CPU and process.wait();
    either constitutes correct forced termination. We only assert that the process
    was NOT allowed to run to completion (exit_code == 0 would be a failure).

    The outer wall-clock check ensures we don't block the test suite even if
    the sandbox kill mechanism fails to fire.
    """
    import signal

    if not _has_timeout(caps):
        pytest.skip(
            f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}; "
            "stress timeout test requires SUPPORTED timeout capability"
        )

    # Allow extra wall-clock headroom for sandbox overhead
    wall_limit = min(_OUTER_TIMEOUT_SEC, 15)
    sandbox_timeout = 3  # 3-second per-sandbox budget

    t0 = time.monotonic()
    result = manager.execute(
        [sys.executable, "-c", "while True: pass"],
        workspace_root=workspace,
        timeout=sandbox_timeout,
    )
    elapsed = time.monotonic() - t0

    # Acceptable forced-kill codes on POSIX:
    #   -1     = our timeout handler
    #   -SIGXCPU (-24 on macOS/Linux) = CPU rlimit
    #   -SIGKILL (-9) = killpg
    # On Windows the backend returns -1 for all timeout kills.
    valid_killed = {-1, -signal.SIGKILL}
    with_sigxcpu = getattr(signal, "SIGXCPU", None)
    if with_sigxcpu is not None:
        valid_killed.add(-with_sigxcpu)

    assert result.exit_code != 0, (
        "CPU-bound loop must NOT exit cleanly (exit_code=0) — the sandbox allowed it to run forever"
    )
    assert result.exit_code in valid_killed or result.exit_code > 0, (
        f"Unexpected exit_code={result.exit_code}; expected a forced-kill code in {valid_killed} "
        "or a positive error code from the sandbox wrapper"
    )
    assert elapsed < wall_limit, (
        f"Sandbox took {elapsed:.1f}s — outer wall-clock limit {wall_limit}s exceeded"
    )


# ---------------------------------------------------------------------------
# Stress: bounded memory allocation
# ---------------------------------------------------------------------------


@pytest.mark.timeout(35)
def test_stress_bounded_memory_allocation(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Allocating more than the memory limit inside the sandbox
    must terminate cleanly or time out.
    """
    if not _has_timeout(caps):
        pytest.skip(f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}")

    if getattr(caps, "memory_limit", "NOT_AVAILABLE") != "SUPPORTED":
        pytest.skip(f"memory_limit is not SUPPORTED on {_SYSTEM}")

    # Allocate 100 MiB with a limit of 50 MiB
    limit_bytes = 50 * 1024 * 1024
    alloc_bytes = 100 * 1024 * 1024
    code = (
        f"data = bytearray({alloc_bytes})\n"
        "print('allocated')\n"
    )

    t0 = time.monotonic()
    result = manager.execute(
        [sys.executable, "-c", code],
        workspace_root=workspace,
        timeout=_OUTER_TIMEOUT_SEC,
        memory_limit=limit_bytes,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < _OUTER_TIMEOUT_SEC, (
        f"Memory allocation test exceeded outer timeout ({_OUTER_TIMEOUT_SEC}s)"
    )
    # The process should be killed by the OS/sandbox for exceeding the limit.
    # Exit codes can be -9 (SIGKILL), or >0 depending on backend wrapper.
    assert result.exit_code != 0, "Process was allowed to exceed memory limit"


# ---------------------------------------------------------------------------
# Stress: bounded child-process spawning
# ---------------------------------------------------------------------------


@pytest.mark.timeout(35)
def test_stress_bounded_child_processes(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Spawning more processes than the limit must fail securely."""
    if not _has_timeout(caps):
        pytest.skip(f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}")

    if getattr(caps, "process_limit", "NOT_AVAILABLE") != "SUPPORTED":
        pytest.skip(f"process_limit is not SUPPORTED on {_SYSTEM}")

    proc_limit = 10
    n_procs = 50

    code = (
        "import subprocess, sys\n"
        "procs = []\n"
        f"for _ in range({n_procs}):\n"
        "    try:\n"
        "        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'])\n"
        "        procs.append(p)\n"
        "    except Exception:\n"
        "        pass\n"
        "for p in procs: p.wait()\n"
        "print(f'spawned {len(procs)}')\n"
    )

    t0 = time.monotonic()
    result = manager.execute(
        [sys.executable, "-c", code],
        workspace_root=workspace,
        timeout=_OUTER_TIMEOUT_SEC,
        process_limit=proc_limit,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < _OUTER_TIMEOUT_SEC, (
        f"Child-process stress test exceeded outer timeout ({_OUTER_TIMEOUT_SEC}s)"
    )
    assert result.exit_code != 0 or f"spawned {n_procs}" not in result.stdout, (
        "Process limit was not enforced"
    )


# ---------------------------------------------------------------------------
# Stress: large output production
# ---------------------------------------------------------------------------


@pytest.mark.timeout(35)
def test_stress_large_stdout_is_truncated(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Producing 500 KiB of stdout must be truncated without hanging.

    This validates that the output-reading thread does not block the test
    suite even when the sandbox produces far more bytes than the limit.
    """
    if not _has_output_limit(caps):
        pytest.skip(
            f"output_limit={getattr(caps, 'output_limit', 'N/A')} on {_SYSTEM}"
        )

    code = "print('x' * 500_000)"

    t0 = time.monotonic()
    result = manager.execute(
        [sys.executable, "-c", code],
        workspace_root=workspace,
        timeout=_OUTER_TIMEOUT_SEC,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < _OUTER_TIMEOUT_SEC
    # Output must be under the raw limit (50 000 bytes) plus the truncation marker
    assert len(result.stdout) < 60_000, (
        "stdout was not truncated — the output reader may be unbounded"
    )
    assert "TRUNCATED" in result.stdout


@pytest.mark.timeout(35)
def test_stress_large_stderr_is_truncated(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """Producing 500 KiB of stderr must be truncated without hanging."""
    if not _has_output_limit(caps):
        pytest.skip(
            f"output_limit={getattr(caps, 'output_limit', 'N/A')} on {_SYSTEM}"
        )

    code = "import sys; sys.stderr.write('y' * 500_000)"

    t0 = time.monotonic()
    result = manager.execute(
        [sys.executable, "-c", code],
        workspace_root=workspace,
        timeout=_OUTER_TIMEOUT_SEC,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < _OUTER_TIMEOUT_SEC
    assert len(result.stderr) < 60_000, (
        "stderr was not truncated — the output reader may be unbounded"
    )
    assert "TRUNCATED" in result.stderr


# ---------------------------------------------------------------------------
# Stress: runaway child cleanup speed
# ---------------------------------------------------------------------------


@pytest.mark.timeout(35)
def test_stress_runaway_child_cleanup_speed(
    manager: SandboxManager, workspace: Path, caps: object
) -> None:
    """When a sandboxed process spawns a long-lived child and the parent times
    out, the entire process group must be reaped in well under the outer limit.

    This verifies that killpg/TerminateJobObject cleanup is not deferred.
    Only applicable on POSIX where killpg is available.
    """
    if not _has_timeout(caps):
        pytest.skip(
            f"timeout={getattr(caps, 'timeout', 'N/A')} on {_SYSTEM}"
        )
    if _SYSTEM not in ("Darwin", "Linux"):
        pytest.skip("Runaway child reaping via killpg is POSIX-only")

    import subprocess

    unique_marker = "88877766655.velix_stress_runaway"
    code = (
        "import subprocess, sys\n"
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({unique_marker})'])\n"
        "import time; time.sleep(10)\n"  # parent also sleeps — ensures timeout fires
    )

    t0 = time.monotonic()
    manager.execute([sys.executable, "-c", code], workspace_root=workspace, timeout=3)
    elapsed = time.monotonic() - t0

    # Allow up to 8 s total wall time (3-s timeout + 5-s overhead headroom)
    assert elapsed < 8, (
        f"Sandbox took {elapsed:.1f}s to clean up runaway child — "
        "expected cleanup within 8 s of timeout"
    )

    # Brief OS reaping pause
    time.sleep(0.5)

    check = subprocess.run(
        ["pgrep", "-f", "[8]8877766655.velix_stress_runaway"],
        capture_output=True,
    )
    assert check.returncode != 0, (
        "Runaway grandchild still alive after sandbox cleanup — killpg may not be working"
    )


# ---------------------------------------------------------------------------
# Safety meta-test: constants are within bounds
# ---------------------------------------------------------------------------


def test_stress_safety_constants_within_bounds() -> None:
    """Assert our safety constants are within the documented limits.

    This test always runs on every platform to catch accidental constant edits.
    """
    assert _OUTER_TIMEOUT_SEC <= 30, (
        f"_OUTER_TIMEOUT_SEC={_OUTER_TIMEOUT_SEC} exceeds the 30-second rule"
    )
    assert _MAX_CHILD_PROCESSES <= 50, (
        f"_MAX_CHILD_PROCESSES={_MAX_CHILD_PROCESSES} exceeds the 50-process rule"
    )
    assert _MEMORY_CAP_BYTES <= 256 * 1024 * 1024, (
        f"_MEMORY_CAP_BYTES={_MEMORY_CAP_BYTES} exceeds 256 MiB"
    )
