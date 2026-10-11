"""
Integration tests proving shadow workspace isolation in VelixAgent.

Verifies:
1. File tools (write_file, edit_file) modify only the shadow tree and leave the host workspace untouched.
2. Shell commands executed via sandbox run within the shadow directory.
3. Exceptions, cancellations, and step failures cleanly destroy the temporary shadow.
4. Host .git directory metadata is completely isolated from the shadow workspace.
5. Default behavior without shadow workspace remains unchanged.
"""

import os
import stat
from pathlib import Path
from typing import Any

import pytest

from velix_agent.core.agent import Agent
from velix_agent.core.application import AutonomousCodingLoop
from velix_agent.core.config import VelixConfig
from velix_agent.core.message import ToolCallPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.orchestrator.models import OrchestratorState
from velix_agent.planning.models import TaskPlan, TaskStep
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxResult
from velix_agent.tools.registry import create_default_tool_registry
from velix_agent.workspace.models import SeedErrorKind, SeedingFailedError
from velix_agent.workspace.seeder import reliable_rmtree, seed_shadow
from velix_agent.workspace.session import ShadowWorkspaceSession


class MockSandboxManager(SandboxManager):
    """Mock sandbox that records the directory in which it executed."""

    def __init__(self) -> None:
        super().__init__(_force_none=True)
        self.executed_dirs: list[Path] = []

    def execute(self, command: list[str], workspace_root: Path | str) -> SandboxResult:
        root = Path(workspace_root).resolve()
        self.executed_dirs.append(root)
        # Emulate command creating a file inside the passed workspace root
        if command and command[0] == "touch" and len(command) > 1:
            (root / command[1]).write_text("TOUCHED")
        return SandboxResult(stdout="ok", stderr="", exit_code=0, command=command)


def test_shadow_workspace_file_writes_leave_host_untouched(tmp_path):
    """
    Prove that write_file and edit_file performed against a shadow workspace
    modify ONLY the shadow workspace, leaving the host workspace byte-identical.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "original.txt").write_text("HOST_VERSION_1")
    (host_ws / "untouched.txt").write_text("REMAINS_SAME")

    host_state_before = {
        p.name: p.read_text() for p in host_ws.iterdir()
    }

    # Open shadow session
    with ShadowWorkspaceSession(host_ws) as shadow_root:
        assert shadow_root.exists()
        assert shadow_root != host_ws

        # Construct registry bound to shadow
        registry = create_default_tool_registry(shadow_root)

        # 1. Edit existing file in shadow
        edit_tool = registry.get_tool("edit_file")
        assert edit_tool is not None
        res_edit = edit_tool.execute(
            file_path="original.txt",
            old_text="HOST_VERSION_1",
            new_text="SHADOW_MUTATION_1",
        )
        assert res_edit.status == "success"

        # 2. Write new file in shadow
        write_tool = registry.get_tool("write_file")
        assert write_tool is not None
        res_write = write_tool.execute(
            file_path="new_shadow_file.txt",
            content="CREATED_IN_SHADOW",
        )
        assert res_write.status == "success"

        # Assert shadow has the changes
        assert (shadow_root / "original.txt").read_text() == "SHADOW_MUTATION_1"
        assert (shadow_root / "new_shadow_file.txt").read_text() == "CREATED_IN_SHADOW"

        # Assert host workspace is completely UNTOUCHED during execution
        host_state_during = {
            p.name: p.read_text() for p in host_ws.iterdir()
        }
        assert host_state_during == host_state_before

    # After session exits, shadow directory is completely wiped
    assert not shadow_root.exists()

    # Host workspace remains identical after session teardown
    host_state_after = {
        p.name: p.read_text() for p in host_ws.iterdir()
    }
    assert host_state_after == host_state_before


def test_shadow_workspace_command_execution_isolated(tmp_path):
    """
    Prove that run_command executed inside the shadow workspace binds to the
    shadow directory and does not affect the host workspace.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "keep.txt").write_text("HOST_DATA")

    mock_sandbox = MockSandboxManager()

    with ShadowWorkspaceSession(host_ws) as shadow_root:
        registry = create_default_tool_registry(shadow_root, sandbox_manager=mock_sandbox)
        cmd_tool = registry.get_tool("run_command")
        assert cmd_tool is not None

        # Execute touch in shadow
        res = cmd_tool.execute(command=["touch", "bash_created.txt"])
        assert res.status == "success"

        # The sandbox executed inside shadow_root
        assert mock_sandbox.executed_dirs == [shadow_root.resolve()]

        # The new file exists in shadow
        assert (shadow_root / "bash_created.txt").exists()

        # The new file does NOT exist in host
        assert not (host_ws / "bash_created.txt").exists()

    # Shadow cleaned up
    assert not shadow_root.exists()
    assert (host_ws / "keep.txt").read_text() == "HOST_DATA"


def test_shadow_workspace_cleanup_on_exception(tmp_path):
    """
    Prove that when an exception occurs during execution, the temporary
    shadow workspace is wiped immediately.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "data.txt").write_text("data")

    captured_shadow: list[Path] = []

    try:
        with ShadowWorkspaceSession(host_ws) as shadow_root:
            captured_shadow.append(shadow_root)
            assert shadow_root.exists()
            raise RuntimeError("Simulated agent execution crash")
    except RuntimeError:
        pass

    assert len(captured_shadow) == 1
    assert not captured_shadow[0].exists(), "Shadow workspace must be cleaned up on exception"
    assert (host_ws / "data.txt").read_text() == "data"


def test_shadow_workspace_git_isolation(tmp_path):
    """
    Prove that host .git metadata is excluded when seeding the shadow workspace
    and cannot be accessed or corrupted.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / ".git").mkdir()
    (host_ws / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0")
    (host_ws / "code.py").write_text("print(1)")

    with ShadowWorkspaceSession(host_ws) as shadow_root:
        # Shadow does NOT have .git
        assert not (shadow_root / ".git").exists()
        assert (shadow_root / "code.py").exists()

        registry = create_default_tool_registry(shadow_root)
        list_tool = registry.get_tool("list_directory")
        assert list_tool is not None

        res = list_tool.execute(dir_path=".")
        assert res.status == "success"
        items = [i["name"] for i in res.data.get("items", [])]
        assert ".git" not in items
        assert "code.py" in items

    # Host .git is intact
    assert (host_ws / ".git" / "config").exists()


class LoopInspectionPlanner:
    """Planner stub providing a preconfigured TaskPlan."""

    def __init__(
        self,
        plan: TaskPlan,
        sandbox_manager: Any = None,
        runtime_manager: Any = None,
    ) -> None:
        self.plan = plan
        self.sandbox_manager = sandbox_manager
        self.runtime_manager = runtime_manager

    def create_plan(self, user_request: str) -> TaskPlan:
        return self.plan


class LoopInspectionProvider:
    """Mock provider that records agent.cwd and agent.tool_registry during execution."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.call_count = 0
        self.agent_ref: Agent | None = None
        self.observed_cwds: list[Path] = []
        self.observed_registries: list[Any] = []
        self.observed_tool_roots: list[Path] = []

    def bind_agent(self, agent: Agent) -> None:
        self.agent_ref = agent

    def generate(self, messages: list[Any], tools: Any = None) -> AgentResponse:
        if self.agent_ref is not None:
            self.observed_cwds.append(self.agent_ref.cwd)
            self.observed_registries.append(self.agent_ref.tool_registry)
            write_tool = self.agent_ref.tool_registry.get_tool("write_file")
            if write_tool and hasattr(write_tool, "workspace_root"):
                self.observed_tool_roots.append(Path(write_tool.workspace_root).resolve())

        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        return AgentResponse(status="success", text="default fallback")


def test_autonomous_coding_loop_shadow_mode_wiring_and_restoration(tmp_path):
    """
    Prove that AutonomousCodingLoop.run() when use_shadow_workspace=True:
    1. Rebinds agent.cwd and agent.tool_registry to the shadow workspace during execution.
    2. Writes made by the agent occur only inside the shadow workspace.
    3. Leaves the host workspace completely untouched.
    4. Restores both agent.cwd and agent.tool_registry to their original references on completion.
    5. Cleans up the temporary shadow workspace directory.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "host_code.py").write_text("print('host')")

    provider = LoopInspectionProvider([
        # Turn 1: request write_file in the workspace
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"file_path": "shadow_output.txt", "content": "SHADOW_PAYLOAD"},
                    id="call_write_1",
                )
            ],
        ),
        # Turn 2: complete the step
        AgentResponse(status="success", text="Step completed"),
    ])

    config = VelixConfig(use_shadow_workspace=True)
    original_registry = create_default_tool_registry(host_ws)
    agent = Agent(Session(), provider=provider, tool_registry=original_registry, config=config)
    agent.cwd = host_ws.resolve()
    provider.bind_agent(agent)

    original_cwd = agent.cwd
    assert original_cwd == host_ws.resolve()

    plan = TaskPlan(
        goal="shadow_test",
        steps=[TaskStep(step_id="step_1", title="write_shadow", description="write a file")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    state = loop.run("execute task in shadow")

    assert state == OrchestratorState.COMPLETED
    assert len(provider.observed_cwds) == 2

    # Verify state during execution
    for i in range(2):
        observed_cwd = provider.observed_cwds[i]
        assert observed_cwd != host_ws.resolve()
        assert provider.observed_registries[i] is not original_registry
        assert provider.observed_tool_roots[i] == observed_cwd.resolve()

    # Verify state after completion: full restoration
    assert agent.cwd == original_cwd
    assert agent.tool_registry is original_registry

    # Verify shadow workspace was wiped
    shadow_root = provider.observed_cwds[0]
    assert not shadow_root.exists()

    # Verify host workspace remains intact and untouched
    assert (host_ws / "host_code.py").read_text() == "print('host')"
    assert not (host_ws / "shadow_output.txt").exists()


def test_autonomous_coding_loop_shadow_mode_exception_restores_state(tmp_path):
    """
    Prove that if an unhandled exception occurs during AutonomousCodingLoop.run()
    in shadow mode:
    1. agent.cwd and agent.tool_registry are restored to their original references in finally.
    2. The temporary shadow workspace is destroyed.
    3. The host workspace remains intact.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "keep.py").write_text("KEEP_HOST_DATA")

    provider = LoopInspectionProvider([
        RuntimeError("Simulated unhandled execution crash"),
    ])

    config = VelixConfig(use_shadow_workspace=True)
    original_registry = create_default_tool_registry(host_ws)
    agent = Agent(Session(), provider=provider, tool_registry=original_registry, config=config)
    agent.cwd = host_ws.resolve()
    provider.bind_agent(agent)

    original_cwd = agent.cwd
    original_tool_registry = agent.tool_registry

    plan = TaskPlan(
        goal="shadow_fail_test",
        steps=[TaskStep(step_id="step_1", title="failing_step", description="will crash")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    with pytest.raises(RuntimeError, match="Simulated unhandled execution crash"):
        loop.run("trigger crash")

    # Verify shadow was active during the first call
    assert len(provider.observed_cwds) == 1
    shadow_root = provider.observed_cwds[0]
    assert shadow_root != host_ws.resolve()

    # Verify full restoration after exception
    assert agent.cwd == original_cwd
    assert agent.tool_registry is original_tool_registry

    # Verify shadow workspace was cleaned up
    assert not shadow_root.exists()

    # Verify host workspace was untouched
    assert (host_ws / "keep.py").read_text() == "KEEP_HOST_DATA"


def test_autonomous_coding_loop_default_non_shadow_mode_unchanged(tmp_path):
    """
    Prove that default non-shadow execution path is preserved:
    1. agent.cwd and agent.tool_registry remain bound to the host workspace throughout.
    2. Tool writes happen directly in the host workspace.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()

    provider = LoopInspectionProvider([
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"file_path": "direct.txt", "content": "DIRECT_WRITE"},
                    id="call_direct_1",
                )
            ],
        ),
        AgentResponse(status="success", text="Completed"),
    ])

    config = VelixConfig(use_shadow_workspace=False)
    original_registry = create_default_tool_registry(host_ws)
    agent = Agent(Session(), provider=provider, tool_registry=original_registry, config=config)
    agent.cwd = host_ws.resolve()
    provider.bind_agent(agent)

    plan = TaskPlan(
        goal="direct_test",
        steps=[TaskStep(step_id="step_1", title="direct_step", description="direct write")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    state = loop.run("direct execution")

    assert state == OrchestratorState.COMPLETED
    assert len(provider.observed_cwds) == 2

    # Execution observed host_ws directly
    for i in range(2):
        assert provider.observed_cwds[i] == host_ws.resolve()
        assert provider.observed_registries[i] is original_registry

    # State unchanged
    assert agent.cwd == host_ws.resolve()
    assert agent.tool_registry is original_registry

    # Direct write succeeded in host
    assert (host_ws / "direct.txt").read_text() == "DIRECT_WRITE"


def test_seeding_mutation_or_read_failure_aborts_session_and_cleans_up(tmp_path):
    """
    SEC-AUDIT-03: When a source file is mutated mid-copy or encounters a fatal read error,
    ShadowWorkspaceSession must fail closed:
    1. Abort session creation by raising SeedingFailedError.
    2. Wipe any partial shadow workspace from disk immediately.
    3. Leave host files untouched.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "stable.txt").write_text("STABLE_CONTENT")
    (host_ws / "mutating.txt").write_text("ORIGINAL_CONTENT")

    shadows_dir = tmp_path / "shadows"
    shadows_dir.mkdir()

    mutated = False

    def chunk_hook(rel_p: str) -> None:
        nonlocal mutated
        if not mutated and "mutating.txt" in rel_p:
            mutated = True
            # Overwrite host file with a different size to trigger mutation detection
            (host_ws / "mutating.txt").write_text("MODIFIED_MID_COPY_LONGER_SIZE")

    with pytest.raises(SeedingFailedError) as exc_info:
        with ShadowWorkspaceSession(
            host_ws,
            tmp_dir=shadows_dir,
            _pre_chunk_hook=chunk_hook,
        ):
            pass

    assert "fatal error" in str(exc_info.value)
    fatal_kinds = [e.kind for e in exc_info.value.errors]
    assert SeedErrorKind.READ_ERROR in fatal_kinds

    # Partial workspace must be completely wiped
    assert list(shadows_dir.iterdir()) == []


def test_autonomous_coding_loop_aborts_when_seeding_fails(tmp_path, monkeypatch):
    """
    SEC-AUDIT-03: When seeding encounters fatal errors, AutonomousCodingLoop.run()
    must never begin controller execution or call agent tools.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "file.txt").write_text("HELLO")

    provider = LoopInspectionProvider([
        AgentResponse(status="success", text="Should never execute"),
    ])
    config = VelixConfig(use_shadow_workspace=True)
    agent = Agent(Session(), provider=provider, config=config)
    agent.cwd = host_ws.resolve()
    provider.bind_agent(agent)

    plan = TaskPlan(
        goal="fail_seed",
        steps=[TaskStep(step_id="step_1", title="step", description="desc")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    # Invalidate seeding by injecting a fatal SeedError
    orig_seed = seed_shadow

    def faulty_seed(*args, **kwargs):
        res = orig_seed(*args, **kwargs)
        from velix_agent.workspace.models import SeedError
        res.errors.append(SeedError("file.txt", SeedErrorKind.READ_ERROR, "Disk I/O error"))
        return res

    monkeypatch.setattr("velix_agent.workspace.session.seed_shadow", faulty_seed)

    with pytest.raises(SeedingFailedError, match="fatal error"):
        loop.run("run failing task")

    # Controller was never started; provider was never called
    assert provider.call_count == 0
    assert agent.cwd == host_ws.resolve()


def test_seeding_interruption_cleans_up_and_reraises(tmp_path):
    """
    SEC-AUDIT-01: When an interruption (KeyboardInterrupt or BaseException) occurs during
    seeding, partial files and temporary shadow directories must be wiped immediately,
    and the original exception must be re-raised without being swallowed.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / "large.txt").write_text("DATA" * 500)

    shadows_dir = tmp_path / "shadows"
    shadows_dir.mkdir()

    def interrupt_hook(rel_p: str) -> None:
        raise KeyboardInterrupt("Simulated user SIGINT during seeding")

    with pytest.raises(KeyboardInterrupt, match="Simulated user SIGINT during seeding"):
        seed_shadow(host_ws, tmp_dir=shadows_dir, _pre_chunk_hook=interrupt_hook)

    # All temporary shadow directories in shadows_dir must be cleaned up
    assert list(shadows_dir.iterdir()) == []


def test_reliable_rmtree_recovers_from_readonly_directory(tmp_path):
    """
    SEC-AUDIT-02: reliable_rmtree must cleanly remove directory structures that contain
    read-only files and read-only subdirectories without failing or leaking directories.
    """
    tree = tmp_path / "tree_to_clean"
    tree.mkdir()
    sub = tree / "readonly_sub"
    sub.mkdir()
    file = sub / "readonly_file.txt"
    file.write_text("LOCKED")

    # Make file read-only and subdirectory read-only (non-writable)
    file.chmod(stat.S_IRUSR)
    sub.chmod(stat.S_IRUSR | stat.S_IXUSR)

    success = reliable_rmtree(tree)
    assert success is True
    assert not tree.exists()


def test_reliable_rmtree_preserves_external_symlink_targets(tmp_path):
    """
    SEC-AUDIT-02: reliable_rmtree must delete symlinks within the tree without following
    them, and must never delete or modify the external targets.
    """
    external_dir = tmp_path / "external_data"
    external_dir.mkdir()
    external_file = external_dir / "preserve.txt"
    external_file.write_text("HOST_SACROSANCT_DATA")

    shadow_dir = tmp_path / "shadow_with_symlinks"
    shadow_dir.mkdir()
    symlink_to_dir = shadow_dir / "link_dir"
    symlink_to_file = shadow_dir / "link_file"
    os.symlink(external_dir, symlink_to_dir)
    os.symlink(external_file, symlink_to_file)

    success = reliable_rmtree(shadow_dir)
    assert success is True
    assert not shadow_dir.exists()

    # External targets must remain completely intact and untouched
    assert external_dir.exists()
    assert external_file.exists()
    assert external_file.read_text() == "HOST_SACROSANCT_DATA"


def test_intentional_exclusions_do_not_abort_session(tmp_path):
    """
    SEC-AUDIT-03: Intentional exclusions (.git metadata, escaping symlinks) must be
    recorded as non-fatal diagnostics and must not prevent session creation.
    """
    host_ws = tmp_path / "host"
    host_ws.mkdir()
    (host_ws / ".git").mkdir()
    (host_ws / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0")
    (host_ws / "main.py").write_text("print('ok')")

    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    os.symlink(outside_dir, host_ws / "escaping_link")

    with ShadowWorkspaceSession(host_ws) as shadow_root:
        assert shadow_root.exists()
        assert (shadow_root / "main.py").exists()
        assert not (shadow_root / ".git").exists()
        assert not (shadow_root / "escaping_link").exists()

    assert not shadow_root.exists()


def test_e2e_sample_project_shadow_mode_disabled(tmp_path):
    """
    End-to-end test on sample project with shadow mode DISABLED:
    Agent tool writes and edits apply directly to the host sample project.
    """
    sample_proj = tmp_path / "sample_project"
    sample_proj.mkdir()
    (sample_proj / "app.py").write_text("def hello():\n    return 'initial'\n")

    provider = LoopInspectionProvider([
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"file_path": "feature.py", "content": "# New feature code\n"},
                    id="call_write_1",
                ),
            ],
        ),
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={"file_path": "app.py", "old_text": "'initial'", "new_text": "'updated'"},
                    id="call_edit_1",
                ),
            ],
        ),
        AgentResponse(status="success", text="All changes complete"),
    ])

    config = VelixConfig(use_shadow_workspace=False)
    registry = create_default_tool_registry(sample_proj)
    agent = Agent(Session(), provider=provider, tool_registry=registry, config=config)
    agent.cwd = sample_proj.resolve()
    provider.bind_agent(agent)

    plan = TaskPlan(
        goal="develop_feature",
        steps=[TaskStep(step_id="1", title="step_1", description="implement feature")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    state = loop.run("build new feature")

    assert state == OrchestratorState.COMPLETED
    # In disabled mode, the host project was modified directly
    assert (sample_proj / "feature.py").read_text() == "# New feature code\n"
    assert (sample_proj / "app.py").read_text() == "def hello():\n    return 'updated'\n"


def test_e2e_sample_project_shadow_mode_enabled_isolation(tmp_path):
    """
    End-to-end test on sample project with shadow mode ENABLED:
    1. Host sample project files remain 100% byte-identical throughout.
    2. Shadow-only created files NEVER appear in the host sample project.
    3. Shell command executed inside shadow executes inside shadow root only.
    4. Temporary shadow workspace directory is cleanly destroyed on exit.
    5. agent.cwd and agent.tool_registry are restored.
    """
    sample_proj = tmp_path / "sample_project"
    sample_proj.mkdir()
    (sample_proj / "app.py").write_text("def hello():\n    return 'initial'\n")
    (sample_proj / "config.json").write_text('{"env": "production"}')

    host_snapshot_before = {
        p.name: p.read_bytes() for p in sample_proj.iterdir()
    }

    mock_sandbox = MockSandboxManager()

    provider = LoopInspectionProvider([
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"file_path": "new_service.py", "content": "class Service: pass\n"},
                    id="call_1",
                ),
            ],
        ),
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={"file_path": "app.py", "old_text": "'initial'", "new_text": "'SHADOW_MUTATION'"},
                    id="call_2",
                ),
            ],
        ),
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="run_command",
                    args={"command": ["touch", "cmd_created.txt"]},
                    id="call_3",
                ),
            ],
        ),
        AgentResponse(status="success", text="Task finished"),
    ])

    config = VelixConfig(use_shadow_workspace=True)
    registry = create_default_tool_registry(sample_proj, sandbox_manager=mock_sandbox)
    agent = Agent(Session(), provider=provider, tool_registry=registry, config=config)
    agent.cwd = sample_proj.resolve()
    provider.bind_agent(agent)

    orig_cwd = agent.cwd
    orig_registry = agent.tool_registry

    plan = TaskPlan(
        goal="safe_feature",
        steps=[TaskStep(step_id="1", title="s1", description="d1")],
    )
    planner = LoopInspectionPlanner(plan, sandbox_manager=mock_sandbox)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    state = loop.run("execute isolated task")

    assert state == OrchestratorState.COMPLETED
    assert len(provider.observed_cwds) == 4

    # The shadow directory existed during execution
    shadow_root = provider.observed_cwds[0]
    assert shadow_root != sample_proj.resolve()

    # The command ran inside the shadow root
    assert mock_sandbox.executed_dirs == [shadow_root.resolve()]

    # After loop exits:
    # 1. Shadow workspace directory is completely gone
    assert not shadow_root.exists()

    # 2. Host sample project files are 100% byte-identical to before
    host_snapshot_after = {
        p.name: p.read_bytes() for p in sample_proj.iterdir()
    }
    assert host_snapshot_after == host_snapshot_before
    assert not (sample_proj / "new_service.py").exists()
    assert not (sample_proj / "cmd_created.txt").exists()

    # 3. Agent cwd and registry references are restored
    assert agent.cwd == orig_cwd
    assert agent.tool_registry is orig_registry


def test_e2e_sample_project_failure_and_interruption_cleanup(tmp_path):
    """
    End-to-end test verifying that controller exceptions and interruptions cleanly
    destroy the shadow workspace and leave the host sample project untouched.
    """
    sample_proj = tmp_path / "sample_project"
    sample_proj.mkdir()
    (sample_proj / "critical.py").write_text("ORIGINAL_CRITICAL_CODE")

    provider = LoopInspectionProvider([
        AgentResponse(
            status="success",
            text="",
            tool_calls=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"file_path": "scratch.txt", "content": "WILL_BE_CLEANED"},
                    id="call_1",
                ),
            ],
        ),
        RuntimeError("Simulated LLM network failure mid-step"),
    ])

    config = VelixConfig(use_shadow_workspace=True)
    registry = create_default_tool_registry(sample_proj)
    agent = Agent(Session(), provider=provider, tool_registry=registry, config=config)
    agent.cwd = sample_proj.resolve()
    provider.bind_agent(agent)

    plan = TaskPlan(
        goal="will_fail",
        steps=[TaskStep(step_id="1", title="s1", description="d1")],
    )
    planner = LoopInspectionPlanner(plan)
    loop = AutonomousCodingLoop(agent=agent, planner=planner)

    with pytest.raises(RuntimeError, match="Simulated LLM network failure mid-step"):
        loop.run("run failing task")

    shadow_root = provider.observed_cwds[0]
    assert not shadow_root.exists(), "Shadow directory must be cleaned up on failure"
    assert (sample_proj / "critical.py").read_text() == "ORIGINAL_CRITICAL_CODE"
    assert not (sample_proj / "scratch.txt").exists()
    assert agent.cwd == sample_proj.resolve()


