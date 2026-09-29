"""Focused unit tests for Gemini provider tool-calling integration."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from velix_agent.core.config import VelixConfig
from velix_agent.core.message import Message, ToolCallPart, ToolResultPart, TextPart
from velix_agent.providers.factory import get_provider
from velix_agent.tools.base import Tool, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SimpleTool(Tool):
    """Minimal Tool stub used only to drive FunctionDeclaration building."""

    def __init__(self, tool_name: str, desc: str, params: dict):
        self._name = tool_name
        self._desc = desc
        self._params = params

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> dict:
        return self._params

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", data={"done": True})


def _make_provider(monkeypatch):
    """Build a GeminiProvider with a mocked google.genai.Client."""
    config = VelixConfig(default_provider="gemini", gemini_api_key=SecretStr("test-key"))
    mock_client = MagicMock()
    monkeypatch.setattr("google.genai.Client", MagicMock(return_value=mock_client))
    provider = get_provider(config)
    return provider, mock_client


def _mock_response(text="", function_calls=None):
    """Build a MagicMock that looks like a GenerateContentResponse."""
    resp = MagicMock()

    parts = []
    if function_calls:
        for fc in function_calls:
            part = MagicMock()
            part.function_call = fc
            part.text = None
            parts.append(part)

    if text:
        text_part = MagicMock()
        text_part.function_call = None
        text_part.text = text
        parts.append(text_part)

    content = MagicMock()
    content.parts = parts

    candidate = MagicMock()
    candidate.content = content

    resp.candidates = [candidate] if parts else []

    resp.usage_metadata = MagicMock()
    resp.usage_metadata.prompt_token_count = 1
    resp.usage_metadata.candidates_token_count = 1
    resp.usage_metadata.total_token_count = 2
    return resp


# ---------------------------------------------------------------------------
# Tests: FunctionDeclaration building (_build_function_declaration)
# ---------------------------------------------------------------------------

def test_build_function_declaration_simple():
    """_build_function_declaration produces correct name, description, params."""
    from velix_agent.providers.gemini import _build_function_declaration
    from google.genai import types

    tool = SimpleTool(
        "list_directory",
        "Lists files in a directory.",
        {
            "type": "object",
            "properties": {
                "dir_path": {"type": "string", "description": "Path to list."},
            },
            "required": ["dir_path"],
        },
    )
    fd = _build_function_declaration(tool)

    assert isinstance(fd, types.FunctionDeclaration)
    assert fd.name == "list_directory"
    assert fd.description == "Lists files in a directory."
    assert "dir_path" in fd.parameters.properties
    assert fd.parameters.required == ["dir_path"]


def test_build_function_declaration_array_param():
    """Array-type parameters are mapped correctly to Gemini Schema."""
    from velix_agent.providers.gemini import _build_function_declaration
    from google.genai import types

    tool = SimpleTool(
        "run_command",
        "Runs a command.",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command list.",
                },
            },
            "required": ["command"],
        },
    )
    fd = _build_function_declaration(tool)
    cmd_schema = fd.parameters.properties["command"]
    assert cmd_schema.type.value == "ARRAY"
    assert cmd_schema.items.type.value == "STRING"


def test_build_function_declaration_multi_param():
    """Multi-parameter tools produce all properties."""
    from velix_agent.providers.gemini import _build_function_declaration

    tool = SimpleTool(
        "edit_file",
        "Edits a file.",
        {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path."},
                "old_text": {"type": "string", "description": "Old."},
                "new_text": {"type": "string", "description": "New."},
            },
            "required": ["file_path", "old_text", "new_text"],
        },
    )
    fd = _build_function_declaration(tool)
    assert set(fd.parameters.properties.keys()) == {"file_path", "old_text", "new_text"}
    assert set(fd.parameters.required) == {"file_path", "old_text", "new_text"}


# ---------------------------------------------------------------------------
# Tests: tools are passed into the Gemini API call
# ---------------------------------------------------------------------------

def test_tools_passed_to_gemini_api(monkeypatch):
    """When tools are supplied, generate_content is called with config.tools set."""
    from google.genai import types

    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="ok")

    tool = SimpleTool(
        "read_file",
        "Reads a file.",
        {
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "Path."}},
            "required": ["file_path"],
        },
    )

    msg = Message(role="user", content="read foo.txt")
    provider.primary.generate([msg], tools=[tool])

    call_args = mock_client.models.generate_content.call_args
    config_arg = call_args[1]["config"]
    assert config_arg.tools is not None
    assert len(config_arg.tools) == 1
    assert isinstance(config_arg.tools[0], types.Tool)
    decls = config_arg.tools[0].function_declarations
    assert len(decls) == 1
    assert decls[0].name == "read_file"


def test_no_tools_means_no_tool_config(monkeypatch):
    """When tools=None, config.tools is not set (falsy)."""
    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="hello")

    msg = Message(role="user", content="hi")
    provider.primary.generate([msg], tools=None)

    call_args = mock_client.models.generate_content.call_args
    config_arg = call_args[1]["config"]
    assert not config_arg.tools


# ---------------------------------------------------------------------------
# Tests: function_call response → ToolCallPart in AgentResponse
# ---------------------------------------------------------------------------

def test_function_call_response_parsed_to_tool_calls(monkeypatch):
    """When Gemini returns function_calls, AgentResponse.tool_calls is populated."""
    provider, mock_client = _make_provider(monkeypatch)

    fc = MagicMock()
    fc.name = "list_directory"
    fc.args = {"dir_path": "."}
    mock_client.models.generate_content.return_value = _mock_response(
        text="", function_calls=[fc]
    )

    tool = SimpleTool("list_directory", "Lists.", {
        "type": "object",
        "properties": {"dir_path": {"type": "string", "description": "path"}},
        "required": ["dir_path"],
    })

    msg = Message(role="user", content="list files")
    resp = provider.primary.generate([msg], tools=[tool])

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert isinstance(tc, ToolCallPart)
    assert tc.tool_name == "list_directory"
    assert tc.args == {"dir_path": "."}


def test_no_function_call_means_no_tool_calls(monkeypatch):
    """When the model returns plain text, tool_calls is None."""
    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(
        text="Here are the files.", function_calls=[]
    )

    msg = Message(role="user", content="list files")
    resp = provider.primary.generate([msg], tools=[])

    assert resp.tool_calls is None


def test_multiple_function_calls_parsed(monkeypatch):
    """Multiple function calls in one response are all captured."""
    provider, mock_client = _make_provider(monkeypatch)

    fc1, fc2 = MagicMock(), MagicMock()
    fc1.name, fc1.args = "read_file", {"file_path": "a.txt"}
    fc2.name, fc2.args = "read_file", {"file_path": "b.txt"}
    mock_client.models.generate_content.return_value = _mock_response(
        text="", function_calls=[fc1, fc2]
    )

    msg = Message(role="user", content="read both")
    resp = provider.primary.generate([msg], tools=[])

    assert resp.tool_calls is not None
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].args["file_path"] == "a.txt"
    assert resp.tool_calls[1].args["file_path"] == "b.txt"


# ---------------------------------------------------------------------------
# Tests: ToolCallPart / ToolResultPart in messages → correct Gemini parts
# ---------------------------------------------------------------------------

def test_tool_call_part_in_assistant_message_becomes_function_call_part(monkeypatch):
    """ToolCallPart in an assistant message is serialised as a function_call Part."""
    from google.genai import types

    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="done")

    messages = [
        Message(role="user", content="list files"),
        Message(
            role="assistant",
            content=[ToolCallPart(tool_name="list_directory", args={"dir_path": "."})],
        ),
        Message(
            role="user",
            content=[ToolResultPart(tool_name="list_directory", data={"items": []})],
        ),
    ]

    provider.primary.generate(messages, tools=[])

    call_args = mock_client.models.generate_content.call_args
    contents = call_args[1]["contents"]

    # contents[1] is the assistant turn — should have a function_call part
    assistant_content = contents[1]
    assert assistant_content.role == "model"
    assert len(assistant_content.parts) == 1
    fc_part = assistant_content.parts[0]
    assert isinstance(fc_part, types.Part)
    assert fc_part.function_call is not None
    assert fc_part.function_call.name == "list_directory"
    assert fc_part.function_call.args == {"dir_path": "."}


def test_tool_result_part_in_user_message_becomes_function_response_part(monkeypatch):
    """ToolResultPart in a user message is serialised as a function_response Part."""
    from google.genai import types

    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="done")

    messages = [
        Message(role="user", content="list files"),
        Message(
            role="assistant",
            content=[ToolCallPart(tool_name="list_directory", args={"dir_path": "."})],
        ),
        Message(
            role="user",
            content=[ToolResultPart(tool_name="list_directory", data={"items": ["a", "b"]})],
        ),
    ]

    provider.primary.generate(messages, tools=[])

    call_args = mock_client.models.generate_content.call_args
    contents = call_args[1]["contents"]

    # contents[2] is the tool-result user turn
    user_content = contents[2]
    assert user_content.role == "user"
    assert len(user_content.parts) == 1
    fr_part = user_content.parts[0]
    assert isinstance(fr_part, types.Part)
    assert fr_part.function_response is not None
    assert fr_part.function_response.name == "list_directory"
    assert fr_part.function_response.response == {"result": {"items": ["a", "b"]}}


def test_tool_result_error_serialised_correctly(monkeypatch):
    """ToolResultPart with an error becomes {\"error\": ...} in function_response."""
    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="sorry")

    messages = [
        Message(role="user", content="list files"),
        Message(
            role="assistant",
            content=[ToolCallPart(tool_name="list_directory", args={"dir_path": "/bad"})],
        ),
        Message(
            role="user",
            content=[ToolResultPart(tool_name="list_directory", error="Access denied")],
        ),
    ]

    provider.primary.generate(messages, tools=[])

    call_args = mock_client.models.generate_content.call_args
    contents = call_args[1]["contents"]
    fr = contents[2].parts[0].function_response
    assert fr.response == {"error": "Access denied"}


# ---------------------------------------------------------------------------
# Tests: automatic_function_calling is always disabled
# ---------------------------------------------------------------------------

def test_automatic_function_calling_is_disabled(monkeypatch):
    """GenerateContentConfig always has automatic_function_calling disabled."""
    from google.genai import types

    provider, mock_client = _make_provider(monkeypatch)
    mock_client.models.generate_content.return_value = _mock_response(text="hi")

    msg = Message(role="user", content="hello")
    provider.primary.generate([msg], tools=[])

    call_args = mock_client.models.generate_content.call_args
    config = call_args[1]["config"]
    assert isinstance(config, types.GenerateContentConfig)
    afc = config.automatic_function_calling
    assert afc is not None
    assert afc.disable is True
