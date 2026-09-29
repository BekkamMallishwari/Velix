
from velix_agent.core.agent import Agent
from velix_agent.core.session import Session
from velix_agent.providers.mock import MockProvider
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.run_command import RunCommandTool


def test_agent_sandbox_integration_flow(tmp_path):
    # Setup Sandbox manager with the temp directory as workspace
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()

    sandbox_manager = SandboxManager()
    run_cmd_tool = RunCommandTool(sandbox=sandbox_manager, workspace_root=workspace)

    registry = ToolRegistry()
    registry.register(run_cmd_tool)

    session = Session()
    provider = MockProvider()

    # We override cwd for InputRouter in agent to avoid path issues
    agent = Agent(session=session, provider=provider, tool_registry=registry)
    agent.cwd = workspace

    # MockProvider is programmed to parse 'execute tool run_command command="xxx"'
    # And when it gets ToolResultPart back, it returns 'Tool succeeded: <data>'

    # MockProvider parses 'execute tool run_command command="echo Integration > test_file"'
    # But RunCommandTool expects a list. Let's make our mock output a list.
    cmd = 'execute tool run_command command="sh,-c,echo Integration > test_file"'

    # This invokes the loop:
    # 1. User: execute tool...
    # 2. Provider -> tool_calls=[run_command, args={command: "echo Integration > test_file"}]
    # 3. Agent resolves RunCommandTool and executes
    # 4. Sandbox manager runs it safely inside workspace
    # 5. Result fed back to Provider
    # 6. Provider -> "Tool succeeded: ..."
    response = agent.respond(cmd)

    assert response.status == "success", f"Agent failed: {response.error} - {response.text}"
    assert "Tool succeeded:" in response.text

    # Verify the file was created in the sandbox
    test_file = workspace / "test_file"
    assert test_file.exists(), (
        f"File not found. Workspace contents: {list(workspace.iterdir())} \n "
        f"Response: {response.text}"
    )
    assert test_file.read_text().strip() == "Integration"

    # Check session history
    msgs = session.context.get_messages()
    # 0: User (execute tool...)
    # 1: Assistant (tool call)
    # 2: User (tool result)
    # 3: Assistant (final text)
    assert len(msgs) == 4

    tool_result = msgs[2]
    assert tool_result.role == "user"
    res_part = tool_result.content[0]
    assert res_part.tool_name == "run_command"
    assert res_part.error is None
