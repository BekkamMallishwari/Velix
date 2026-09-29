from velix_agent.core.agent import Agent
from velix_agent.core.session import Session
from velix_agent.providers.mock import MockProvider
from velix_agent.sandbox.manager import SandboxManager
from velix_agent.tools.edit_file import EditFileTool
from velix_agent.tools.read_file import ReadFileTool
from velix_agent.tools.registry import ToolRegistry
from velix_agent.tools.run_command import RunCommandTool
from velix_agent.tools.write_file import WriteFileTool

def test_agent_file_ops_integration_flow(tmp_path):
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()

    sandbox_manager = SandboxManager()
    run_cmd_tool = RunCommandTool(sandbox=sandbox_manager, workspace_root=workspace)
    read_file_tool = ReadFileTool(workspace_root=workspace)
    edit_file_tool = EditFileTool(workspace_root=workspace)
    write_file_tool = WriteFileTool(workspace_root=workspace)

    registry = ToolRegistry()
    registry.register(run_cmd_tool)
    registry.register(read_file_tool)
    registry.register(edit_file_tool)
    registry.register(write_file_tool)

    session = Session()
    provider = MockProvider()

    agent = Agent(session=session, provider=provider, tool_registry=registry)
    agent.cwd = workspace

    # We will simulate a sequential conversation by mocking the agent's response to commands

    # 1. Write File
    cmd_write = 'execute tool write_file file_path=hello.txt,content="Hello World"'
    resp_write = agent.respond(cmd_write)
    assert resp_write.status == "success"
    assert (workspace / "hello.txt").read_text() == "Hello World"

    # 2. Read File
    cmd_read = 'execute tool read_file file_path=hello.txt'
    resp_read = agent.respond(cmd_read)
    assert resp_read.status == "success"

    # 3. Edit File
    cmd_edit = 'execute tool edit_file file_path=hello.txt,old_text=World,new_text=Agent'
    resp_edit = agent.respond(cmd_edit)
    assert resp_edit.status == "success"
    assert (workspace / "hello.txt").read_text() == "Hello Agent"

    # 4. Run Command to verify
    # Because of mock.py's split(","), we do command="sh,-c,cat hello.txt"
    cmd_run = 'execute tool run_command command="/usr/bin/python3,-c,print(open(\'hello.txt\').read())"'
    resp_run = agent.respond(cmd_run)
    assert resp_run.status == "success"

    # Verify session history
    msgs = session.context.get_messages()
    assert len(msgs) == 16  # 4 * (User, Asst ToolCall, User ToolRes, Asst Final)

    # Check that RunCommand actually executed via sandbox and saw "Hello Agent"
    run_res_msg = msgs[14]
    assert run_res_msg.role == "user"
    assert run_res_msg.content[0].tool_name == "run_command"
    assert "Hello Agent" in run_res_msg.content[0].data["stdout"]
