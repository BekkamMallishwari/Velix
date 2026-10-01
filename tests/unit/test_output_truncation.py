from velix_agent.core.agent import _truncate_tool_result
from velix_agent.tools.base import ToolResult


def test_small_output_unchanged():
    res = ToolResult(status="success", data={"stdout": "small output", "stderr": ""})
    res_trunc = _truncate_tool_result(res, max_size=100)
    assert res_trunc.data["stdout"] == "small output"


def test_exactly_at_limit_output():
    max_size = 50
    content = "a" * max_size
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert res_trunc.data["content"] == content


def test_just_above_limit():
    max_size = 50
    content = "a" * (max_size + 1)
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["content"]) == max_size
    assert "[Output truncated" in res_trunc.data["content"]
    assert res_trunc.data["content"].startswith("a")


def test_large_stdout_truncated():
    max_size = 60
    stdout = "x" * 100
    res = ToolResult(status="success", data={"stdout": stdout, "exit_code": 0, "command": ["ls"]})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["stdout"]) == max_size
    assert "[Output truncated" in res_trunc.data["stdout"]
    assert res_trunc.data["stdout"].startswith("x")
    # Metadata preserved
    assert res_trunc.data["exit_code"] == 0
    assert res_trunc.data["command"] == ["ls"]


def test_large_stderr_truncated_keeps_end():
    max_size = 60
    stderr = "beginning" + "x" * 100 + "END_ERROR"
    res = ToolResult(status="success", data={"stderr": stderr})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["stderr"]) == max_size
    assert "[Output truncated" in res_trunc.data["stderr"]
    assert res_trunc.data["stderr"].endswith("END_ERROR")
    assert not res_trunc.data["stderr"].startswith("beginning")


def test_read_file_large_file_truncated():
    max_size = 70
    content = "line1\n" + "y" * 100 + "\nline3"
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.data["content"]) == max_size
    assert "[Output truncated" in res_trunc.data["content"]
    assert res_trunc.data["content"].startswith("line1\n")


def test_unicode_output_handled_safely():
    max_size = 60
    content = "🌍" * 100
    res = ToolResult(status="success", data={"content": content})
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    # the exact length might vary slightly depending on emoji length,
    # but it's bound by max_size (characters)
    assert len(res_trunc.data["content"]) <= max_size
    assert "[Output truncated" in res_trunc.data["content"]


def test_existing_tool_errors_truncated():
    max_size = 60
    error_msg = "start" + "e" * 100 + "end"
    res = ToolResult(status="error", error=error_msg)
    res_trunc = _truncate_tool_result(res, max_size=max_size)
    assert len(res_trunc.error) == max_size
    assert "[Output truncated" in res_trunc.error
    assert res_trunc.error.endswith("end")
