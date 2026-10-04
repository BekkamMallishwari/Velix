from pathlib import Path

from velix_agent.core.agent import Agent
from velix_agent.core.message import Message, ToolCallPart, ToolResultPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.session import Session
from velix_agent.providers.base import Provider
from velix_agent.tools.base import Tool
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.search_files import SearchFilesTool


class MaxIterationsProvider(Provider):
    def generate(self, messages: list[Message], tools: list[Tool] | None = None) -> AgentResponse:
        return AgentResponse(
            text="Still thinking...",
            status="success",
            tool_calls=[
                ToolCallPart(tool_name="search_files", args={"query": "test"}, id="call_infinite")
            ],
        )


def test_max_iterations_exceeded(tmp_path: Path) -> None:
    """Verify that the agent forcibly stops a runaway tool loop after MAX_ITERATIONS."""
    registry = ToolRegistry()
    registry.register(SearchFilesTool(workspace_root=tmp_path))
    session = Session.create()
    agent = Agent(session, provider=MaxIterationsProvider(), tool_registry=registry)

    res = agent.respond("Start infinite loop")
    assert res.status == "error"
    assert "exceeded maximum tool iterations" in res.text


class UnknownToolProvider(Provider):
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, messages: list[Message], tools: list[Tool] | None = None) -> AgentResponse:
        self.call_count += 1
        if self.call_count == 1:
            return AgentResponse(
                text="Trying fake tool",
                status="success",
                tool_calls=[ToolCallPart(tool_name="made_up_tool", args={}, id="call_unknown")],
            )
        else:
            return AgentResponse(text="Done", status="success")


def test_unknown_tool(tmp_path: Path) -> None:
    """Verify the agent safely catches unknown tools and feeds back an error to the LLM."""
    registry = ToolRegistry()
    session = Session.create()
    provider = UnknownToolProvider()
    agent = Agent(session, provider=provider, tool_registry=registry)

    res = agent.respond("Trigger unknown tool")
    assert res.status == "success"

    msgs = session.context.get_messages()
    # Find the ToolResultPart fed back to the LLM
    found_error = False
    for msg in msgs:
        if msg.role == "user" and isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, ToolResultPart) and part.tool_name == "made_up_tool":
                    assert "Unknown tool" in str(part.error)
                    found_error = True
    assert found_error


class MalformedArgsProvider(Provider):
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, messages: list[Message], tools: list[Tool] | None = None) -> AgentResponse:
        self.call_count += 1
        if self.call_count == 1:
            # Pass completely invalid args to search_files
            return AgentResponse(
                text="Sending bad args",
                status="success",
                tool_calls=[
                    ToolCallPart(tool_name="search_files", args={"query": None}, id="call_bad_args")
                ],
            )
        return AgentResponse(text="Done", status="success")


def test_malformed_arguments(tmp_path: Path) -> None:
    """Verify the agent handles malformed tool arguments without crashing."""
    registry = ToolRegistry()
    registry.register(SearchFilesTool(workspace_root=tmp_path))
    session = Session.create()
    provider = MalformedArgsProvider()
    agent = Agent(session, provider=provider, tool_registry=registry)

    agent.respond("Trigger bad args")

    msgs = session.context.get_messages()
    found_error = False
    for msg in msgs:
        if msg.role == "user" and isinstance(msg.content, list):
            for part in msg.content:
                if isinstance(part, ToolResultPart) and part.tool_name == "search_files":
                    # search_files explicitly catches empty query and returns error
                    assert "Missing or empty required argument" in str(part.error)
                    found_error = True
    assert found_error


class SearchFilesE2EProvider(Provider):
    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, messages: list[Message], tools: list[Tool] | None = None) -> AgentResponse:
        self.call_count += 1
        if self.call_count == 1:
            # Turn 1: Decide to search for 'super_secret_password'
            return AgentResponse(
                text="I will search for the password.",
                status="success",
                tool_calls=[
                    ToolCallPart(
                        tool_name="search_files",
                        args={"query": "super_secret_password"},
                        id="call_search",
                    )
                ],
            )
        elif self.call_count == 2:
            # Turn 2: Observe the results and provide final answer
            last_msg = messages[-1]
            assert last_msg.role == "user"
            result_part = last_msg.content[0]

            assert isinstance(result_part, ToolResultPart)
            assert result_part.tool_name == "search_files"
            assert result_part.data is not None
            assert result_part.data["total_matches"] == 1
            assert result_part.data["matches"][0]["file"] == "config.txt"

            return AgentResponse(text="Found it in config.txt!", status="success")

        return AgentResponse(text="Failsafe", status="success")


def test_search_files_e2e_flow(tmp_path: Path) -> None:
    """Verify a complete E2E conversational loop utilizing search_files."""
    # Setup workspace
    (tmp_path / "config.txt").write_text("db_pass = 'super_secret_password'\n")

    registry = ToolRegistry()
    registry.register(SearchFilesTool(workspace_root=tmp_path))
    session = Session.create()
    provider = SearchFilesE2EProvider()
    agent = Agent(session, provider=provider, tool_registry=registry)

    res = agent.respond("Find the database password")

    assert res.status == "success"
    assert res.text == "Found it in config.txt!"
    assert provider.call_count == 2
