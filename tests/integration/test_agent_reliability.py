from collections.abc import Callable
from pathlib import Path

from velix_agent.core.agent import Agent
from velix_agent.core.message import Message, ToolCallPart, ToolResultPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.providers.base import Provider
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxResult
from velix_agent.tools.base import Tool
from velix_agent.tools.edit_file import EditFileTool
from velix_agent.tools.list_directory import ListDirectoryTool
from velix_agent.tools.read_file import ReadFileTool
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.run_command import RunCommandTool


class StatefulMockProvider(Provider):
    """
    A deterministic provider that executes a pre-programmed sequence of steps.
    Each step is a callable that receives the current conversation history
    and returns the AgentResponse for that turn.
    """

    def __init__(self, steps: list[Callable[[list[Message]], AgentResponse]]) -> None:
        self.steps = steps
        self.call_count = 0
        self.history_received: list[list[Message]] = []

    def generate(self, messages: list[Message], tools: list[Tool] | None = None) -> AgentResponse:
        self.history_received.append(messages)
        if self.call_count < len(self.steps):
            step_fn = self.steps[self.call_count]
            self.call_count += 1
            return step_fn(messages)
        return AgentResponse(text="Failsafe stop", status="success")


# ---------------------------------------------------------------------------
# SCENARIO A — NONEXISTENT FILE RECOVERY
# ---------------------------------------------------------------------------
def test_scenario_a_nonexistent_file_recovery(tmp_path: Path) -> None:
    # Setup workspace
    (tmp_path / "actual_config.json").write_text('{"db_host": "localhost"}')

    registry = ToolRegistry()
    registry.register(ReadFileTool(workspace_root=tmp_path))
    registry.register(ListDirectoryTool(workspace_root=tmp_path))

    def step1(messages: list[Message]) -> AgentResponse:
        return AgentResponse(
            text="Reading config...",
            status="success",
            tool_calls=[
                ToolCallPart(tool_name="read_file", args={"file_path": "config.json"}, id="call_1")
            ],
        )

    def step2(messages: list[Message]) -> AgentResponse:
        # Verify the tool error is present
        last_msg = messages[-1]
        assert last_msg.role == "user"
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "read_file"
        assert res_part.error is not None
        assert "not found" in str(res_part.error).lower()

        return AgentResponse(
            text="File not found, listing directory.",
            status="success",
            tool_calls=[
                ToolCallPart(tool_name="list_directory", args={"dir_path": "."}, id="call_2")
            ],
        )

    def step3(messages: list[Message]) -> AgentResponse:
        # Verify directory listing
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "list_directory"
        assert res_part.error is None

        # Read the correct file
        return AgentResponse(
            text="Found it, reading actual_config.json.",
            status="success",
            tool_calls=[
                ToolCallPart(
                    tool_name="read_file", args={"file_path": "actual_config.json"}, id="call_3"
                )
            ],
        )

    def step4(messages: list[Message]) -> AgentResponse:
        # Verify successful read
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "read_file"
        assert res_part.error is None
        assert "localhost" in str(res_part.data)

        return AgentResponse(text="The database host is localhost.", status="success")

    provider = StatefulMockProvider([step1, step2, step3, step4])
    agent = Agent(Session.create(), provider=provider, tool_registry=registry)

    res = agent.respond("Read the database config")

    assert res.status == "success"
    assert res.text == "The database host is localhost."
    assert provider.call_count == 4


# ---------------------------------------------------------------------------
# SCENARIO B — MULTI-FILE REFACTORING
# ---------------------------------------------------------------------------
def test_scenario_b_multi_file_refactoring(tmp_path: Path) -> None:
    # Setup workspace
    utils_dir = tmp_path / "utils"
    utils_dir.mkdir()
    (utils_dir / "log.py").write_text("class OldLogger:\n    pass\n")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("from utils.log import OldLogger\n")

    registry = ToolRegistry()
    registry.register(EditFileTool(workspace_root=tmp_path))

    def step1(messages: list[Message]) -> AgentResponse:
        return AgentResponse(
            text="Renaming logger in utils/log.py",
            status="success",
            tool_calls=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={
                        "file_path": "utils/log.py",
                        "old_text": "OldLogger",
                        "new_text": "NewLogger",
                    },
                    id="call_1",
                )
            ],
        )

    def step2(messages: list[Message]) -> AgentResponse:
        # Verify first edit
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "edit_file"
        assert res_part.error is None

        return AgentResponse(
            text="Updating import in src/main.py",
            status="success",
            tool_calls=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={
                        "file_path": "src/main.py",
                        "old_text": "OldLogger",
                        "new_text": "NewLogger",
                    },
                    id="call_2",
                )
            ],
        )

    def step3(messages: list[Message]) -> AgentResponse:
        # Verify second edit
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "edit_file"
        assert res_part.error is None

        return AgentResponse(text="Refactoring complete", status="success")

    provider = StatefulMockProvider([step1, step2, step3])
    agent = Agent(Session.create(), provider=provider, tool_registry=registry)

    res = agent.respond("Rename the logging utility and update its import in main.py")

    assert res.status == "success"
    assert res.text == "Refactoring complete"
    assert provider.call_count == 3

    assert "class NewLogger:" in (utils_dir / "log.py").read_text()
    assert "from utils.log import NewLogger" in (src_dir / "main.py").read_text()


# ---------------------------------------------------------------------------
# SCENARIO C — TEST FAILURE AND SELF-CORRECTION
# ---------------------------------------------------------------------------
class StatefulMockSandboxManager(SandboxManager):
    def __init__(self) -> None:
        super().__init__(_force_none=True)
        self.call_count = 0

    def execute(
        self, command: list[str], workspace_root: str | Path, timeout: int = 30
    ) -> SandboxResult:
        self.call_count += 1
        if self.call_count == 1:
            return SandboxResult(
                stdout="",
                stderr="AssertionError: 1 != 2",
                exit_code=1,
                command=command,
            )
        return SandboxResult(
            stdout="All tests passed",
            stderr="",
            exit_code=0,
            command=command,
        )


def test_scenario_c_test_failure_and_self_correction(tmp_path: Path) -> None:
    (tmp_path / "test_math.py").write_text("def test_math():\n    assert 1 == 2\n")

    registry = ToolRegistry()
    registry.register(EditFileTool(workspace_root=tmp_path))
    registry.register(RunCommandTool(sandbox=StatefulMockSandboxManager(), workspace_root=tmp_path))

    def step1(messages: list[Message]) -> AgentResponse:
        return AgentResponse(
            text="Running tests",
            status="success",
            tool_calls=[
                ToolCallPart(tool_name="run_command", args={"command": ["pytest"]}, id="call_1")
            ],
        )

    def step2(messages: list[Message]) -> AgentResponse:
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "run_command"
        assert res_part.error is None  # The tool ran successfully
        assert res_part.data["exit_code"] == 1
        assert "AssertionError" in res_part.data["stderr"]
        assert res_part.data["success"] is False

        return AgentResponse(
            text="Fixing the test",
            status="success",
            tool_calls=[
                ToolCallPart(
                    tool_name="edit_file",
                    args={
                        "file_path": "test_math.py",
                        "old_text": "assert 1 == 2",
                        "new_text": "assert 1 == 1",
                    },
                    id="call_2",
                )
            ],
        )

    def step3(messages: list[Message]) -> AgentResponse:
        return AgentResponse(
            text="Running tests again",
            status="success",
            tool_calls=[
                ToolCallPart(tool_name="run_command", args={"command": ["pytest"]}, id="call_3")
            ],
        )

    def step4(messages: list[Message]) -> AgentResponse:
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "run_command"
        assert res_part.error is None
        assert res_part.data["exit_code"] == 0
        assert res_part.data["success"] is True

        return AgentResponse(text="Tests passing", status="success")

    provider = StatefulMockProvider([step1, step2, step3, step4])
    agent = Agent(Session.create(), provider=provider, tool_registry=registry)

    res = agent.respond("Run the test suite and fix any failing tests")

    assert res.status == "success"
    assert res.text == "Tests passing"
    assert provider.call_count == 4
    assert "assert 1 == 1" in (tmp_path / "test_math.py").read_text()


# ---------------------------------------------------------------------------
# SCENARIO D — LARGE TOOL OUTPUT
# ---------------------------------------------------------------------------
class MassiveOutputSandboxManager(SandboxManager):
    def __init__(self) -> None:
        super().__init__(_force_none=True)

    def execute(
        self, command: list[str], workspace_root: str | Path, timeout: int = 30
    ) -> SandboxResult:
        # Return 15MB of text
        huge_text = "x" * (15 * 1024 * 1024)
        return SandboxResult(
            stdout=huge_text,
            stderr="",
            exit_code=0,
            command=command,
        )


def test_scenario_d_large_tool_output(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(
        RunCommandTool(sandbox=MassiveOutputSandboxManager(), workspace_root=tmp_path)
    )

    def step1(messages: list[Message]) -> AgentResponse:
        return AgentResponse(
            text="Reading huge log",
            status="success",
            tool_calls=[
                ToolCallPart(
                    tool_name="run_command", args={"command": ["cat", "huge.log"]}, id="call_1"
                )
            ],
        )

    def step2(messages: list[Message]) -> AgentResponse:
        last_msg = messages[-1]
        res_part = last_msg.content[0]
        assert isinstance(res_part, ToolResultPart)
        assert res_part.tool_name == "run_command"
        assert res_part.error is None

        # Verify the output was successfully truncated by existing agent limits
        # We don't know the exact max_size offhand (default is large but < 10MB)
        # We just need to assert it didn't blow up and it contains the truncation warning.
        assert "Truncated" in str(res_part.data) or "[Output truncated" in str(res_part.data)

        # Also ensure it's not actually 15MB.
        assert len(str(res_part.data)) < 1 * 1024 * 1024  # definitely strictly < 1MB

        return AgentResponse(text="Done inspecting", status="success")

    provider = StatefulMockProvider([step1, step2])
    agent = Agent(Session.create(), provider=provider, tool_registry=registry)

    res = agent.respond("Inspect the workspace")

    assert res.status == "success"
    assert res.text == "Done inspecting"
    assert provider.call_count == 2
