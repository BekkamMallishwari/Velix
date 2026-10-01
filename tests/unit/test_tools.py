"""Unit tests for the Tool Layer."""

import pytest

from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError, SandboxResult
from velix_agent.tools.base import Tool, ToolResult
from velix_agent.tools.list_directory import ListDirectoryTool
from velix_agent.tools.read_file import ReadFileTool
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.run_command import RunCommandTool


class DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "A dummy tool."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", data=kwargs)


class MockSandboxManager(SandboxManager):
    def __init__(self, should_fail=False):
        super().__init__(_force_none=True)
        self.should_fail = should_fail
        self.last_command = None

    def execute(self, command, workspace_root):
        self.last_command = command
        if self.should_fail:
            raise SandboxError("Mock sandbox rejection")
        return SandboxResult(
            stdout="mock output",
            stderr="",
            exit_code=0,
            command=command,
        )


@pytest.fixture
def workspace(tmp_path):
    """Fixture providing a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# --- Test ToolResult ---


def test_tool_result_validation():
    with pytest.raises(ValueError, match="Invalid status"):
        ToolResult(status="invalid")  # type: ignore

    with pytest.raises(ValueError, match="Error response must include error details"):
        ToolResult(status="error")


# --- Test ReadFileTool ---


def test_read_file_tool_success(workspace):
    test_file = workspace / "test.txt"
    test_file.write_text("Hello, world!")
    tool = ReadFileTool(workspace_root=workspace)

    # Relative path
    result = tool.execute(file_path="test.txt")
    assert result.status == "success"
    assert result.data["content"] == "Hello, world!"

    # Absolute path
    result2 = tool.execute(file_path=str(test_file))
    assert result2.status == "success"
    assert result2.data["content"] == "Hello, world!"


def test_read_file_tool_not_found(workspace):
    tool = ReadFileTool(workspace_root=workspace)
    result = tool.execute(file_path="missing.txt")
    assert result.status == "error"
    assert "File not found" in result.error


def test_read_file_tool_is_directory(workspace):
    subdir = workspace / "subdir"
    subdir.mkdir()
    tool = ReadFileTool(workspace_root=workspace)
    result = tool.execute(file_path="subdir")
    assert result.status == "error"
    assert "Path is a directory" in result.error


def test_read_file_tool_traversal(workspace, tmp_path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("secret")

    tool = ReadFileTool(workspace_root=workspace)
    result = tool.execute(file_path="../secret.txt")
    assert result.status == "error"
    assert "outside the allowed workspace" in result.error

    result2 = tool.execute(file_path=str(secret_file))
    assert result2.status == "error"
    assert "outside the allowed workspace" in result2.error


def test_read_file_tool_empty(workspace):
    test_file = workspace / "empty.txt"
    test_file.write_text("")
    tool = ReadFileTool(workspace_root=workspace)
    result = tool.execute(file_path="empty.txt")
    assert result.status == "success"
    assert result.data["content"] == ""


def test_read_file_tool_unicode(workspace):
    test_file = workspace / "unicode.txt"
    test_file.write_text("hello 🌍", encoding="utf-8")
    tool = ReadFileTool(workspace_root=workspace)
    result = tool.execute(file_path="unicode.txt")
    assert result.status == "success"
    assert result.data["content"] == "hello 🌍"


# --- Test ListDirectoryTool ---


def test_list_directory_tool_success(workspace):
    (workspace / "file1.txt").touch()
    (workspace / "dir1").mkdir()
    tool = ListDirectoryTool(workspace_root=workspace)

    result = tool.execute(dir_path=".")
    assert result.status == "success"
    items = result.data["items"]
    assert len(items) == 2
    assert items[0]["name"] == "dir1"
    assert items[0]["type"] == "directory"
    assert items[1]["name"] == "file1.txt"
    assert items[1]["type"] == "file"


def test_list_directory_tool_empty(workspace):
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path=".")
    assert result.status == "success"
    assert result.data["items"] == []


def test_list_directory_tool_not_found(workspace):
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path="missing_dir")
    assert result.status == "error"
    assert "Directory not found" in result.error


def test_list_directory_tool_is_file(workspace):
    test_file = workspace / "test.txt"
    test_file.touch()
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path="test.txt")
    assert result.status == "error"
    assert "Path is a file" in result.error


def test_list_directory_tool_traversal(workspace, tmp_path):
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path="..")
    assert result.status == "error"
    assert "outside the allowed workspace" in result.error


def test_list_directory_tool_nested(workspace):
    nested = workspace / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "file.txt").touch()
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path="a/b")
    assert result.status == "success"
    assert len(result.data["items"]) == 1
    assert result.data["items"][0]["name"] == "file.txt"


def test_list_directory_tool_git_protection(workspace):
    git_dir = workspace / ".git"
    git_dir.mkdir()
    (git_dir / "config").touch()
    tool = ListDirectoryTool(workspace_root=workspace)
    result = tool.execute(dir_path=".git")
    assert result.status == "error"
    assert "protected .git paths" in result.error


# --- Test RunCommandTool ---


def test_run_command_tool_success(workspace):
    mock_sandbox = MockSandboxManager()
    tool = RunCommandTool(sandbox=mock_sandbox, workspace_root=workspace)

    result = tool.execute(command=["echo", "test"])
    assert result.status == "success"
    assert result.data["stdout"] == "mock output"
    assert result.data["exit_code"] == 0
    assert result.data["success"] is True
    assert mock_sandbox.last_command == ["echo", "test"]


def test_run_command_tool_rejection(workspace):
    mock_sandbox = MockSandboxManager(should_fail=True)
    tool = RunCommandTool(sandbox=mock_sandbox, workspace_root=workspace)

    result = tool.execute(command=["rm", "-rf", "/"])
    assert result.status == "error"
    assert "Sandbox rejected execution" in result.error


def test_run_command_tool_invalid_args(workspace):
    mock_sandbox = MockSandboxManager()
    tool = RunCommandTool(sandbox=mock_sandbox, workspace_root=workspace)

    result = tool.execute(command="echo test")  # String instead of list
    assert result.status == "error"
    assert "must be a list of strings" in result.error


# --- Test ToolRegistry ---


def test_tool_registry():
    registry = ToolRegistry()
    tool = DummyTool()

    registry.register(tool)
    assert registry.get_tool("dummy_tool") is tool
    assert len(registry.list_tools()) == 1

    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)


def test_tool_registry_unknown():
    registry = ToolRegistry()
    assert registry.get_tool("missing_tool") is None


def test_tool_registry_builtins():
    registry = ToolRegistry()
    from velix_agent.tools.edit_file import EditFileTool
    from velix_agent.tools.list_directory import ListDirectoryTool
    from velix_agent.tools.read_file import ReadFileTool
    from velix_agent.tools.write_file import WriteFileTool

    registry.register(ReadFileTool(workspace_root="/tmp"))
    registry.register(WriteFileTool(workspace_root="/tmp"))
    registry.register(EditFileTool(workspace_root="/tmp"))
    registry.register(ListDirectoryTool(workspace_root="/tmp"))

    tools = registry.list_tools()
    names = {t.name for t in tools}
    assert {"read_file", "write_file", "edit_file", "list_directory"}.issubset(names)
