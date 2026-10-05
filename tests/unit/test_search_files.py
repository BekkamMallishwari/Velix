from pathlib import Path
from unittest.mock import patch

import pytest

from velix_agent.tools.search_files import SearchFilesTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text("def hello():\n    print('world')\n")
    (tmp_path / "README.md").write_text("Hello world!")

    # Excluded dir
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("hello world")

    # Nested dir
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "main.py").write_text("import os\n\ndef main():\n    hello()\n")

    # Binary file
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRhello")

    return tmp_path


def test_basic_search(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello")
    assert res.status == "success"
    assert res.data["total_matches"] == 2  # app.py, src/main.py

    files = {m["file"] for m in res.data["matches"]}
    assert "app.py" in files
    assert "src/main.py" in files
    assert ".git/config" not in files


def test_regex_search(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query=r"def \w+\(", is_regex=True)
    assert res.status == "success"
    assert res.data["total_matches"] == 2


def test_ignore_case(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="HELLO", ignore_case=True)
    assert res.status == "success"
    assert res.data["total_matches"] == 3


def test_file_pattern(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", file_pattern="*.py")
    assert res.status == "success"
    assert res.data["total_matches"] == 2
    files = {m["file"] for m in res.data["matches"]}
    assert "README.md" not in files


def test_invalid_regex(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="[unclosed", is_regex=True)
    assert res.status == "error"
    assert res.error and "Invalid regular expression" in res.error


def test_out_of_bounds_directory(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", directory="../outside")
    assert res.status == "error"
    assert res.error and "Access denied" in res.error


def test_empty_query(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="")
    assert res.status == "error"
    assert res.error and "Argument 'query' cannot be empty." in res.error


def test_match_limit(workspace: Path) -> None:
    # Generate 150 matches, limit is 100
    content = "match\n" * 150
    (workspace / "big.txt").write_text(content)

    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="match")
    assert res.status == "success"
    assert res.data["total_matches"] == 100
    assert res.data["truncated"] is True


def test_scanned_files_limit_truncation(workspace: Path) -> None:
    # We mock MAX_SCANNED_FILES to 2 to easily hit the limit.
    with patch("velix_agent.tools.search_files.MAX_SCANNED_FILES", 2):
        tool = SearchFilesTool(workspace_root=workspace)
        res = tool.execute(query="hello")
        assert res.status == "success"
        # We hit the scan limit, so truncated MUST be True
        assert res.data["truncated"] is True


def test_scanned_files_limit_boundary(workspace: Path) -> None:
    # Test completing below the limit.
    with patch("velix_agent.tools.search_files.MAX_SCANNED_FILES", 100):
        tool = SearchFilesTool(workspace_root=workspace)
        res = tool.execute(query="hello")
        assert res.status == "success"
        assert res.data["truncated"] is False


def test_regex_line_length_cap(workspace: Path) -> None:
    # Test that regex matching respects MAX_REGEX_LINE_LENGTH
    # We write a line with 2005 characters, and test if regex matches characters at the end
    long_line = "A" * 2000 + "match_me_at_end"
    (workspace / "long.txt").write_text(long_line)

    with patch("velix_agent.tools.search_files.MAX_REGEX_LINE_LENGTH", 2000):
        tool = SearchFilesTool(workspace_root=workspace)

        # Literal search should still find it (no truncation is applied to non-regex searches)
        res_literal = tool.execute(query="match_me_at_end", is_regex=False)
        assert res_literal.status == "success"
        assert res_literal.data["total_matches"] == 1

        # Regex search should NOT find it because it gets truncated at 2000 chars
        res_regex = tool.execute(query="match_me_at_end", is_regex=True)
        assert res_regex.status == "success"
        assert res_regex.data["total_matches"] == 0

def test_missing_query(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute()
    assert res.status == "error"
    assert "Missing required argument: 'query'" in res.error

def test_query_wrong_type(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query=123)
    assert res.status == "error"
    assert "Argument 'query' must be a string." in res.error

def test_directory_wrong_type(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", directory=123)
    assert res.status == "error"
    assert "Argument 'directory' must be a string." in res.error

def test_file_pattern_wrong_type(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", file_pattern=123)
    assert res.status == "error"
    assert "Argument 'file_pattern' must be a string." in res.error

def test_max_results_wrong_type(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", max_results="100")
    assert res.status == "error"
    assert "Argument 'max_results' must be an integer." in res.error

    res_bool = tool.execute(query="hello", max_results=True)
    assert res_bool.status == "error"
    assert "Argument 'max_results' must be an integer." in res_bool.error

def test_max_results_invalid_value(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", max_results=0)
    assert res.status == "error"
    assert "Argument 'max_results' must be positive." in res.error

def test_regex_wrong_type(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", is_regex="true")
    assert res.status == "error"
    assert "Argument 'is_regex' must be a boolean." in res.error

    res2 = tool.execute(query="hello", regex="true")
    assert res2.status == "error"
    assert "Argument 'regex' must be a boolean." in res2.error

def test_valid_max_results(workspace: Path) -> None:
    tool = SearchFilesTool(workspace_root=workspace)
    res = tool.execute(query="hello", max_results=1)
    assert res.status == "success"
    assert res.data["total_matches"] == 1
    assert res.data["truncated"] is True
