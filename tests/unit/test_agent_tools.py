from velix_agent.core.agent import Agent
from velix_agent.core.message import ToolCallPart, ToolResultPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.providers.base import Provider
from velix_agent.tools.base import Tool, ToolResult
from velix_agent.tools.registry import ToolRegistry


class DummyProvider(Provider):
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def generate(self, messages, tools=None):
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


class DummyTool(Tool):
    def __init__(self, name="dummy", will_fail=False):
        self._name = name
        self.will_fail = will_fail
        self.call_count = 0
        self.last_args = None

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return "Dummy tool"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        self.call_count += 1
        self.last_args = kwargs
        if self.will_fail:
            return ToolResult(status="error", error="Tool intentionally failed")
        return ToolResult(status="success", data=f"Result of {self._name}")


def test_agent_normal_request_without_tools():
    session = Session()
    provider = DummyProvider([AgentResponse(text="Normal response")])
    agent = Agent(session=session, provider=provider)

    resp = agent.respond("hello")

    assert resp.status == "success"
    assert resp.text == "Normal response"
    assert provider.call_count == 1

    # Session context should have user and assistant
    msgs = session.context.get_messages()
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"


def test_agent_successful_tool_invocation():
    session = Session()
    tool = DummyTool("get_weather")
    registry = ToolRegistry()
    registry.register(tool)

    provider = DummyProvider(
        [
            AgentResponse(
                text="Let me check",
                tool_calls=[ToolCallPart(tool_name="get_weather", args={"location": "Tokyo"})],
            ),
            AgentResponse(text="The weather in Tokyo is sunny."),
        ]
    )

    agent = Agent(session=session, provider=provider, tool_registry=registry)
    resp = agent.respond("What is the weather in Tokyo?")

    assert resp.status == "success"
    assert resp.text == "The weather in Tokyo is sunny."
    assert provider.call_count == 2
    assert tool.call_count == 1
    assert tool.last_args == {"location": "Tokyo"}

    msgs = session.context.get_messages()
    assert len(msgs) == 4
    # User: What is the weather
    # Assistant: Let me check (with tool call)
    # User: tool result
    # Assistant: The weather is sunny


def test_agent_unknown_tool():
    session = Session()
    provider = DummyProvider(
        [
            AgentResponse(text="", tool_calls=[ToolCallPart(tool_name="unknown_tool", args={})]),
            AgentResponse(text="I got an error about an unknown tool."),
        ]
    )

    agent = Agent(session=session, provider=provider)
    agent.respond("do something")

    assert provider.call_count == 2
    msgs = session.context.get_messages()
    tool_result_msg = msgs[2]
    assert tool_result_msg.role == "user"
    assert isinstance(tool_result_msg.content[0], ToolResultPart)
    assert tool_result_msg.content[0].error == "Unknown tool: unknown_tool"


def test_agent_tool_failure():
    session = Session()
    tool = DummyTool("failing_tool", will_fail=True)
    registry = ToolRegistry()
    registry.register(tool)

    provider = DummyProvider(
        [
            AgentResponse(text="", tool_calls=[ToolCallPart(tool_name="failing_tool", args={})]),
            AgentResponse(text="Tool failed gracefully."),
        ]
    )

    agent = Agent(session=session, provider=provider, tool_registry=registry)
    agent.respond("run failing tool")

    assert tool.call_count == 1
    msgs = session.context.get_messages()
    tool_result_msg = msgs[2]
    assert tool_result_msg.content[0].error == "Tool intentionally failed"


def test_agent_tool_exception():
    session = Session()

    class ExceptionTool(Tool):
        @property
        def name(self):
            return "exc_tool"

        @property
        def description(self):
            return ""

        @property
        def parameters(self):
            return {"type": "object", "properties": {}}

        def execute(self, **kwargs):
            raise ValueError("Something crashed")

    registry = ToolRegistry()
    registry.register(ExceptionTool())

    provider = DummyProvider(
        [
            AgentResponse(text="", tool_calls=[ToolCallPart(tool_name="exc_tool", args={})]),
            AgentResponse(text="Tool raised exception."),
        ]
    )

    agent = Agent(session=session, provider=provider, tool_registry=registry)
    agent.respond("crash")

    msgs = session.context.get_messages()
    assert "Execution error: Something crashed" in msgs[2].content[0].error


def test_agent_max_iterations():
    session = Session()
    tool = DummyTool("loop_tool")
    registry = ToolRegistry()
    registry.register(tool)

    # Provider always returns a tool call
    class InfiniteProvider(Provider):
        def generate(self, messages, tools=None):
            return AgentResponse(
                text="looping", tool_calls=[ToolCallPart(tool_name="loop_tool", args={})]
            )

    agent = Agent(session=session, provider=InfiniteProvider(), tool_registry=registry)
    resp = agent.respond("start loop")

    assert resp.status == "error"
    assert resp.error == "Max iterations reached."
    assert tool.call_count == 5  # MAX_ITERATIONS is 5


def test_agent_multiple_tool_calls_in_one_response():
    """Provider returns two ToolCallParts in a single response.

    Both tools must execute exactly once, their results must be returned in the
    same user message, and both tool_call_ids must be preserved.
    Context layout expected:
        msgs[0]  user  (original request)
        msgs[1]  assistant  (tool calls A + B)
        msgs[2]  user  (tool results for A and B)
        msgs[3]  assistant  (final answer)
    """
    tool_a = DummyTool("tool_a")
    tool_b = DummyTool("tool_b")
    registry = ToolRegistry()
    registry.register(tool_a)
    registry.register(tool_b)

    provider = DummyProvider(
        [
            AgentResponse(
                text="Calling both tools",
                tool_calls=[
                    ToolCallPart(tool_name="tool_a", args={}, id="id_a"),
                    ToolCallPart(tool_name="tool_b", args={}, id="id_b"),
                ],
            ),
            AgentResponse(text="Both results received."),
        ]
    )

    session = Session()
    agent = Agent(session=session, provider=provider, tool_registry=registry)
    resp = agent.respond("run both tools")

    assert resp.status == "success"
    assert resp.text == "Both results received."
    assert provider.call_count == 2

    # Both tools executed exactly once
    assert tool_a.call_count == 1
    assert tool_b.call_count == 1

    msgs = session.context.get_messages()
    assert len(msgs) == 4

    # msgs[1] — assistant message contains both ToolCallParts
    assistant_msg = msgs[1]
    assert assistant_msg.role == "assistant"
    tc_parts = [p for p in assistant_msg.content if isinstance(p, ToolCallPart)]
    assert len(tc_parts) == 2
    tc_names = {p.tool_name for p in tc_parts}
    assert tc_names == {"tool_a", "tool_b"}

    # msgs[2] — user message contains both ToolResultParts
    result_msg = msgs[2]
    assert result_msg.role == "user"
    tr_parts = [p for p in result_msg.content if isinstance(p, ToolResultPart)]
    assert len(tr_parts) == 2

    # Both tool_call_ids are preserved
    result_ids = {p.tool_call_id for p in tr_parts}
    assert result_ids == {"id_a", "id_b"}

    # msgs[3] — final assistant message
    assert msgs[3].role == "assistant"


def test_agent_tool_call_id_preserved_in_result():
    """The tool_call_id on ToolResultPart must exactly equal the id on ToolCallPart."""
    specific_id = "abc-123-xyz"

    tool = DummyTool("echo_tool")
    registry = ToolRegistry()
    registry.register(tool)

    provider = DummyProvider(
        [
            AgentResponse(
                text="",
                tool_calls=[ToolCallPart(tool_name="echo_tool", args={}, id=specific_id)],
            ),
            AgentResponse(text="Done."),
        ]
    )

    session = Session()
    agent = Agent(session=session, provider=provider, tool_registry=registry)
    agent.respond("echo")

    msgs = session.context.get_messages()
    # msgs[2] is the user message carrying the tool result
    result_msg = msgs[2]
    assert result_msg.role == "user"
    result_part = result_msg.content[0]
    assert isinstance(result_part, ToolResultPart)
    assert result_part.tool_call_id == specific_id


def test_agent_context_unchanged_on_max_iterations():
    """When MAX_ITERATIONS is exhausted, the session context must remain empty.

    Partial tool-call rounds must not be committed to the context.
    """
    session = Session()
    tool = DummyTool("loop_tool")
    registry = ToolRegistry()
    registry.register(tool)

    class InfiniteProvider(Provider):
        def generate(self, messages, tools=None):
            return AgentResponse(
                text="looping", tool_calls=[ToolCallPart(tool_name="loop_tool", args={})]
            )

    agent = Agent(session=session, provider=InfiniteProvider(), tool_registry=registry)
    resp = agent.respond("start loop")

    # Failure response is correct
    assert resp.status == "error"
    assert resp.error == "Max iterations reached."
    # Tool executed MAX_ITERATIONS times
    assert tool.call_count == 5
    # Context must be completely empty — no partial messages committed
    assert session.context.get_messages() == []
