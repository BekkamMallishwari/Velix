from velix_agent.tools.edit_file import EditFileTool
from velix_agent.tools.read_file import MAX_READ_FILE_SIZE, ReadFileTool
from velix_agent.tools.write_file import WriteFileTool


def test_write_file_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", content="Hello world")

    assert res.status == "success"
    assert (workspace / "test.txt").read_text() == "Hello world"
    assert res.data["size"] == len("Hello world")


def test_write_file_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="../outside/test.txt", content="Hello world")

    assert res.status == "error"
    assert "outside the allowed workspace" in res.error


def test_write_file_is_dir(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "dir").mkdir()

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="dir", content="Hello")

    assert res.status == "error"
    assert "Path is a directory" in res.error


def test_write_file_git_protection(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path=".git/config", content="hacked")

    assert res.status == "error"
    assert "protected .git paths" in res.error


def test_write_file_creates_parent_dirs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="a/b/c/test.txt", content="Hello")

    assert res.status == "success"
    assert (workspace / "a/b/c/test.txt").read_text() == "Hello"


def test_edit_file_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("This is an old string here.", encoding="utf-8")

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="old string", new_text="new text")

    assert res.status == "success"
    assert target.read_text(encoding="utf-8") == "This is an new text here."


def test_edit_file_not_found(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="missing.txt", old_text="old", new_text="new")

    assert res.status == "error"
    assert "File not found" in res.error


def test_edit_file_old_text_missing(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("Hello world", encoding="utf-8")

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="missing", new_text="new")

    assert res.status == "error"
    assert "not found in the file" in res.error


def test_edit_file_ambiguous(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("cat dog cat", encoding="utf-8")

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="cat", new_text="bat")

    assert res.status == "error"
    assert "Ambiguous replacement" in res.error
    assert target.read_text(encoding="utf-8") == "cat dog cat"


def test_edit_file_git_protection(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git_dir = workspace / ".git"
    git_dir.mkdir()
    target = git_dir / "config"
    target.write_text("content", encoding="utf-8")

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path=".git/config", old_text="content", new_text="hacked")

    assert res.status == "error"
    assert "protected .git paths" in res.error


def test_write_file_overwrite(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("old content")
    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", content="new content")
    assert res.status == "success"
    assert target.read_text() == "new content"


def test_write_file_unicode(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test_unicode.txt", content="hello 🌍")
    assert res.status == "success"
    assert (workspace / "test_unicode.txt").read_text(encoding="utf-8") == "hello 🌍"


def test_write_file_failure_no_corruption(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("initial content")

    # Mock write_text to raise an exception
    def mock_write_text(*args, **kwargs):
        raise OSError("Disk full")

    import pathlib

    monkeypatch.setattr(pathlib.Path, "write_text", mock_write_text)

    tool = WriteFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", content="new content")
    assert res.status == "error"
    assert "Unexpected error" in res.error
    assert target.read_text() == "initial content"


def test_edit_file_empty_replacement(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("hello world")
    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text=" world", new_text="")
    assert res.status == "success"
    assert target.read_text() == "hello"


def test_edit_file_invalid_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="../outside.txt", old_text="old", new_text="new")
    assert res.status == "error"
    assert "outside the allowed workspace" in res.error


def test_edit_file_failure_unchanged(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("hello world")

    def mock_write_text(*args, **kwargs):
        raise OSError("Disk full")

    import pathlib

    monkeypatch.setattr(pathlib.Path, "write_text", mock_write_text)

    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="world", new_text="universe")
    assert res.status == "error"
    assert target.read_text() == "hello world"


def test_edit_file_unicode(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("hello 🌍", encoding="utf-8")
    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="🌍", new_text="🌎")
    assert res.status == "success"
    assert target.read_text(encoding="utf-8") == "hello 🌎"


def test_edit_file_invalid_utf8(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_bytes(b"\xff\xfe\xff")
    tool = EditFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt", old_text="a", new_text="b")
    assert res.status == "error"
    assert "not valid UTF-8" in res.error


# --- ReadFileTool Tests ---


def test_read_file_success(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_text("hello world")

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt")

    assert res.status == "success"
    assert res.data["content"] == "hello world"


def test_read_file_missing(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="missing.txt")

    assert res.status == "error"
    assert "File not found" in res.error


def test_read_file_is_dir(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "dir").mkdir()

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="dir")

    assert res.status == "error"
    assert "Path is a directory" in res.error


def test_read_file_invalid_utf8(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "test.txt"
    target.write_bytes(b"\xff\xfe\xff")

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="test.txt")

    assert res.status == "error"
    assert "not valid UTF-8" in res.error


def test_read_file_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test.txt").write_text("secret")

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="../outside/test.txt")

    assert res.status == "error"
    assert "outside the allowed workspace" in res.error


def test_read_file_oversized(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "large.txt"
    target.write_text(
        "small text"
    )  # The actual file is small so read_text wouldn't crash if it got there

    # Mock the stat result to appear massive
    import pathlib

    original_stat = pathlib.Path.stat

    class FakeStat:
        @property
        def st_size(self):
            return MAX_READ_FILE_SIZE + 1

        @property
        def st_mode(self):
            return 33188

    def mock_stat(self, *args, **kwargs):
        if "large.txt" in str(self):
            return FakeStat()
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", mock_stat)

    read_text_called = False

    original_read_text = pathlib.Path.read_text

    def mock_read_text(self, *args, **kwargs):
        nonlocal read_text_called
        if "large.txt" in str(self):
            read_text_called = True
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", mock_read_text)

    tool = ReadFileTool(workspace_root=workspace)
    res = tool.execute(file_path="large.txt")

    assert res.status == "error"
    assert "maximum allowed read size" in res.error
    assert not read_text_called, "read_text() was called despite the size limit"


# --- Argument Validation Tests ---


def test_read_file_invalid_args(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = ReadFileTool(workspace_root=workspace)

    res1 = tool.execute()
    assert res1.status == "error"
    assert "Missing required argument" in res1.error

    res2 = tool.execute(file_path=123)
    assert res2.status == "error"
    assert "must be a string" in res2.error


def test_write_file_invalid_args(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = WriteFileTool(workspace_root=workspace)

    res1 = tool.execute(content="abc")
    assert res1.status == "error"
    assert "Missing required argument: 'file_path'" in res1.error

    res2 = tool.execute(file_path="test.txt")
    assert res2.status == "error"
    assert "Missing required argument: 'content'" in res2.error

    res3 = tool.execute(file_path="test.txt", content=123)
    assert res3.status == "error"
    assert "Argument 'content' must be a string" in res3.error

    res4 = tool.execute(file_path=123, content="abc")
    assert res4.status == "error"
    assert "Argument 'file_path' must be a string" in res4.error


def test_edit_file_invalid_args(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = EditFileTool(workspace_root=workspace)

    res1 = tool.execute(old_text="a", new_text="b")
    assert res1.status == "error"
    assert "Missing required argument: 'file_path'" in res1.error

    res2 = tool.execute(file_path="test.txt", new_text="b")
    assert res2.status == "error"
    assert "Missing required argument: 'old_text'" in res2.error

    res3 = tool.execute(file_path="test.txt", old_text="a")
    assert res3.status == "error"
    assert "Missing required argument: 'new_text'" in res3.error

    res4 = tool.execute(file_path="test.txt", old_text=123, new_text="b")
    assert res4.status == "error"
    assert "must be strings" in res4.error

    res5 = tool.execute(file_path=123, old_text="a", new_text="b")
    assert res5.status == "error"
    assert "Argument 'file_path' must be a string" in res5.error

    res6 = tool.execute(file_path="test.txt", old_text="", new_text="b")
    assert res6.status == "error"
    assert "Argument 'old_text' cannot be empty." in res6.error
