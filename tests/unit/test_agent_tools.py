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
