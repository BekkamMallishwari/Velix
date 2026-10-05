from velix_agent.core.agent import _truncate_tool_result
from velix_agent.tools.base import ToolResult


def test_small_output_unchanged():
    res = ToolResult(status="success", data={"stdout": "small output", "stderr": ""})
    res_trunc = _truncate_tool_result(res, max_size=300)
    assert res_trunc.data["stdout"] == "small output"


def test_exactly_at_limit_output():
    max_size = 300
    specific_max = max(0, max_size - 256)
    content = "a" * specific_max
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert res_trunc.data["content"] == content


def test_just_above_limit():
    max_size = 500
    specific_max = max(0, max_size - 256)
    content = "a" * (specific_max + 1)
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["content"]) == specific_max
    assert "[Output truncated" in res_trunc.data["content"]
    assert res_trunc.data["content"].startswith("a")


def test_large_stdout_truncated():
    max_size = 360
    specific_max = max(0, max_size - 256)
    stdout = "x" * 200
    res = ToolResult(status="success", data={"stdout": stdout, "exit_code": 0, "command": ["ls"]})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["stdout"]) == specific_max
    assert "[Output truncated" in res_trunc.data["stdout"]
    assert res_trunc.data["stdout"].startswith("x")
    # Metadata preserved
    assert res_trunc.data["exit_code"] == 0
    assert res_trunc.data["command"] == ["ls"]


def test_large_stderr_truncated_keeps_end():
    max_size = 360
    specific_max = max(0, max_size - 256)
    stderr = "beginning" + "x" * 200 + "END_ERROR"
    res = ToolResult(status="success", data={"stderr": stderr})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["stderr"]) == specific_max
    assert "[Output truncated" in res_trunc.data["stderr"]
    assert res_trunc.data["stderr"].endswith("END_ERROR")
    assert not res_trunc.data["stderr"].startswith("beginning")


def test_read_file_large_file_truncated():
    max_size = 370
    specific_max = max(0, max_size - 256)
    content = "line1\n" + "y" * 200 + "\nline3"
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["content"]) == specific_max
    assert "[Output truncated" in res_trunc.data["content"]
    assert res_trunc.data["content"].startswith("line1\n")


def test_unicode_output_handled_safely():
    max_size = 500
    content = "🌍" * 300
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert isinstance(res_trunc.data, str)
    assert "[Output truncated" in res_trunc.data


def test_existing_tool_errors_truncated():
    max_size = 60
    error_msg = "start" + "e" * 100 + "end"
    res = ToolResult(status="error", error=error_msg)
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.error) == max_size
    assert "[Output truncated" in res_trunc.error
    assert res_trunc.error.endswith("end")


# --- Bare-string data ---


def test_bare_string_data_below_limit_unchanged():
    res = ToolResult(status="success", data="short string")
    result = _truncate_tool_result(res, max_size=100)
    assert result is res  # identity: no new object created


def test_bare_string_data_exactly_at_limit_unchanged():
    max_size = 50
    res = ToolResult(status="success", data="a" * max_size)
    result = _truncate_tool_result(res, max_size=max_size)
    assert result is res  # at the boundary, no truncation


def test_bare_string_data_above_limit_truncated():
    max_size = 60
    res = ToolResult(status="success", data="z" * 200)
    result = _truncate_tool_result(res, max_size=max_size)
    assert isinstance(result.data, str)
    assert len(result.data) == max_size
    assert "[Output truncated" in result.data
    assert result.data.startswith("z")
    assert result.status == "success"
    assert result.error is None


# --- data=None ---


def test_data_none_returned_unchanged():
    res = ToolResult(status="success", data=None)
    result = _truncate_tool_result(res, max_size=100)
    assert result is res  # identity: no new object created
    assert result.data is None


# --- Structured list values must not be modified ---


def test_command_list_not_modified():
    """RunCommandTool.data["command"] must pass through intact."""
    command = ["git", "diff", "--stat"]
    res = ToolResult(
        status="success",
        data={
            "command": command,
            "exit_code": 0,
            "stdout": "x" * 5,
            "stderr": "",
            "success": True,
        },
    )
    result = _truncate_tool_result(res, max_size=500)
    assert result.data["command"] == command


def test_items_list_not_modified():
    """ListDirectoryTool.data["items"] must pass through intact."""
    items = [{"name": f"file{i}.py", "type": "file"} for i in range(10)]
    res = ToolResult(status="success", data={"items": items})
    result = _truncate_tool_result(res, max_size=1000)
    assert result.data["items"] == items
    assert result is res  # no dict keys touched → same object returned


# --- Global Serialized Size Tests ---

def test_large_list_truncated():
    items = [{"name": f"file{i}.py", "type": "file"} for i in range(100)]
    res = ToolResult(status="success", data={"items": items})
    result = _truncate_tool_result(res, max_size=200)

    assert isinstance(result.data, str)
    assert "[Output truncated" in result.data
    assert len(result.data) <= 200

def test_large_nested_dict_list_truncated():
    large_data = {
        "metadata": {"source": "test", "tags": ["a", "b", "c"]},
        "results": [
            {"id": i, "value": "x" * 50} for i in range(50)
        ]
    }
    res = ToolResult(status="success", data=large_data)
    result = _truncate_tool_result(res, max_size=300)

    assert isinstance(result.data, str)
    assert "[Output truncated" in result.data
    assert len(result.data) <= 300
