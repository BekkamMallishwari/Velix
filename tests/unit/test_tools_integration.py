from velix_agent.sandbox.manager import SandboxManager
from velix_agent.sandbox.result import SandboxError, SandboxResult
from velix_agent.tools.edit_file import EditFileTool
from velix_agent.tools.list_directory import ListDirectoryTool
from velix_agent.tools.read_file import ReadFileTool
from velix_agent.tools.run_command import RunCommandTool
from velix_agent.tools.write_file import WriteFileTool


class MockSandboxManager(SandboxManager):
    def __init__(self, should_fail=False):
        super().__init__(_force_none=True)
        self.should_fail = should_fail

    def execute(self, command, workspace_root):
        if self.should_fail:
            raise SandboxError("Sandbox rejected execution")
        return SandboxResult(
            stdout="mock",
            stderr="",
            exit_code=0,
            command=command,
        )


def test_write_then_read(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_tool = WriteFileTool(workspace_root=workspace)
    read_tool = ReadFileTool(workspace_root=workspace)

    write_res = write_tool.execute(file_path="hello.txt", content="world")
    assert write_res.status == "success"

    read_res = read_tool.execute(file_path="hello.txt")
    assert read_res.status == "success"
    assert read_res.data["content"] == "world"


def test_write_edit_read(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_tool = WriteFileTool(workspace_root=workspace)
    edit_tool = EditFileTool(workspace_root=workspace)
    read_tool = ReadFileTool(workspace_root=workspace)

    write_tool.execute(file_path="test.txt", content="hello world")
    edit_tool.execute(file_path="test.txt", old_text="world", new_text="universe")
    read_res = read_tool.execute(file_path="test.txt")

    assert read_res.data["content"] == "hello universe"


def test_list_write_list(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    list_tool = ListDirectoryTool(workspace_root=workspace)
    write_tool = WriteFileTool(workspace_root=workspace)

    res1 = list_tool.execute(dir_path=".")
    assert len(res1.data["items"]) == 0

    write_tool.execute(file_path="a.txt", content="A")
    write_tool.execute(file_path="b.txt", content="B")

    res2 = list_tool.execute(dir_path=".")
    items = sorted([item["name"] for item in res2.data["items"]])
    assert items == ["a.txt", "b.txt"]


def test_run_command_workspace_integration(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    sandbox = MockSandboxManager()
    run_tool = RunCommandTool(sandbox=sandbox, workspace_root=workspace)

    res = run_tool.execute(command=["ls", "-la"])
    assert res.status == "success"


def test_failed_path_validation_then_valid(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_tool = WriteFileTool(workspace_root=workspace)

    res1 = write_tool.execute(file_path="../outside.txt", content="bad")
    assert res1.status == "error"

    res2 = write_tool.execute(file_path="inside.txt", content="good")
    assert res2.status == "success"
    assert (workspace / "inside.txt").read_text() == "good"


def test_failed_edit_leaves_file_unchanged(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_tool = WriteFileTool(workspace_root=workspace)
    edit_tool = EditFileTool(workspace_root=workspace)

    write_tool.execute(file_path="test.txt", content="content")

    # Try to edit non-existent text
    edit_tool.execute(file_path="test.txt", old_text="missing", new_text="new")

    # File should be unchanged
    assert (workspace / "test.txt").read_text() == "content"
