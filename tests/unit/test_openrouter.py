from unittest.mock import MagicMock

import pytest
from openai import (
    AuthenticationError,
    RateLimitError,
)

from velix_agent.core.message import Message, ToolCallPart, ToolResultPart
from velix_agent.providers.errors import (
    ProviderAuthError,
    ProviderQuotaError,
)
from velix_agent.providers.openrouter import OpenRouterProvider


@pytest.fixture
def mock_openai_client(monkeypatch):
    mock_client_class = MagicMock()
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    monkeypatch.setattr("openai.OpenAI", mock_client_class)
    return mock_client_class, mock_client


def test_openrouter_construction(mock_openai_client):
    provider = OpenRouterProvider(api_key="test-key", model="test-model")
    mock_client_class, _ = mock_openai_client
    mock_client_class.assert_called_once_with(
        api_key="test-key", base_url="https://openrouter.ai/api/v1"
    )
    assert provider.model == "test-model"


def _mock_response(text="test", tool_calls=None):
    resp = MagicMock()
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = tool_calls
    resp.choices = [MagicMock(message=msg)]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    resp.model = "test-model"
    return resp


def test_normal_text_response(mock_openai_client):
    _, mock_client = mock_openai_client
    mock_client.chat.completions.create.return_value = _mock_response(text="Hello world")

    provider = OpenRouterProvider(api_key="test-key")
    res = provider.generate([Message(role="user", content="Hi")])

    assert res.text == "Hello world"
    assert res.status == "success"
    assert res.tool_calls is None

    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Hi"}]}]


def test_one_tool_call(mock_openai_client):
    _, mock_client = mock_openai_client

    tc_mock = MagicMock()
    tc_mock.id = "call_123"
    tc_mock.function.name = "write_file"
    tc_mock.function.arguments = """{"file_path": "test.txt"}"""
    tc_mock.model_dump.return_value = {
        "id": "call_123",
        "type": "function",
        "function": {"name": "write_file", "arguments": """{"file_path": "test.txt"}"""},
    }

    mock_client.chat.completions.create.return_value = _mock_response(text="", tool_calls=[tc_mock])

    provider = OpenRouterProvider(api_key="test-key")
    res = provider.generate([Message(role="user", content="Hi")])

    assert res.tool_calls is not None
    assert len(res.tool_calls) == 1
    tc = res.tool_calls[0]
    assert tc.tool_name == "write_file"
    assert tc.id == "call_123"
    assert tc.args == {"file_path": "test.txt"}
    assert "openrouter_raw_tool_call" in tc.provider_metadata


def test_multiple_tool_calls(mock_openai_client):
    _, mock_client = mock_openai_client

    tc1 = MagicMock()
    tc1.id = "call_1"
    tc1.function.name = "tool1"
    tc1.function.arguments = """{}"""
    tc1.model_dump.return_value = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "tool1", "arguments": "{}"},
    }

    tc2 = MagicMock()
    tc2.id = "call_2"
    tc2.function.name = "tool2"
    tc2.function.arguments = """{}"""
    tc2.model_dump.return_value = {
        "id": "call_2",
        "type": "function",
        "function": {"name": "tool2", "arguments": "{}"},
    }

    mock_client.chat.completions.create.return_value = _mock_response(
        text="", tool_calls=[tc1, tc2]
    )

    provider = OpenRouterProvider(api_key="test-key")
    res = provider.generate([Message(role="user", content="Hi")])

    assert res.tool_calls is not None
    assert len(res.tool_calls) == 2
    assert res.tool_calls[0].tool_name == "tool1"
    assert res.tool_calls[1].tool_name == "tool2"


def test_tool_result_round_trip(mock_openai_client):
    _, mock_client = mock_openai_client
    mock_client.chat.completions.create.return_value = _mock_response(text="Done")

    provider = OpenRouterProvider(api_key="test-key")

    tc = ToolCallPart(
        tool_name="tool1",
        args={},
        id="call_1",
        provider_metadata={
            "openrouter_raw_tool_call": {
                "id": "call_1",
                "type": "function",
                "function": {"name": "tool1", "arguments": "{}"},
            }
        },
    )

    tr = ToolResultPart(tool_name="tool1", data={"status": "ok"}, tool_call_id="call_1")

    messages = [
        Message(role="user", content="Hi"),
        Message(role="assistant", content=[tc]),
        Message(role="user", content=[tr]),
    ]

    provider.generate(messages)

    kwargs = mock_client.chat.completions.create.call_args[1]
    msgs = kwargs["messages"]

    assert len(msgs) == 3
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "tool1", "arguments": "{}"}}
    ]
    assert msgs[2]["role"] == "tool"
    assert msgs[2]["tool_call_id"] == "call_1"
    assert msgs[2]["content"] == """{"status": "ok"}"""


def test_api_auth_error(mock_openai_client):
    _, mock_client = mock_openai_client
    mock_client.chat.completions.create.side_effect = AuthenticationError(
        message="bad auth", response=MagicMock(), body=None
    )

    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderAuthError):
        provider.generate([Message(role="user", content="Hi")])


def test_api_quota_error(mock_openai_client):
    _, mock_client = mock_openai_client
    mock_client.chat.completions.create.side_effect = RateLimitError(
        message="insufficient quota", response=MagicMock(), body=None
    )

    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderQuotaError):
        provider.generate([Message(role="user", content="Hi")])


def test_tool_call_strict_json(mock_openai_client):
    _, mock_client = mock_openai_client

    tc_mock = MagicMock()
    tc_mock.id = "call_123"
    tc_mock.function.name = "write_file"
    tc_mock.function.arguments = (
        '{"file_path": "test.txt", "content": "def hello():\\n    return 4"}'
    )
    tc_mock.model_dump.return_value = {
        "id": "call_123",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": '{"file_path": "test.txt", "content": "def hello():\\n    return 4"}',
        },
    }

    mock_client.chat.completions.create.return_value = _mock_response(text="", tool_calls=[tc_mock])

    provider = OpenRouterProvider(api_key="test-key")
    res = provider.generate([Message(role="user", content="Hi")])

    assert res.tool_calls is not None
    assert len(res.tool_calls) == 1
    tc = res.tool_calls[0]
    assert tc.tool_name == "write_file"
    assert "content" in tc.args
    assert "def hello():\n    return 4" in tc.args["content"]


def test_empty_response(mock_openai_client):
    from velix_agent.providers.errors import ProviderAPIError

    _, mock_client = mock_openai_client

    mock_client.chat.completions.create.return_value = _mock_response(text="", tool_calls=None)

    provider = OpenRouterProvider(api_key="test-key")
    with pytest.raises(ProviderAPIError, match="OpenRouter returned an empty response"):
        provider.generate([Message(role="user", content="Hi")])
