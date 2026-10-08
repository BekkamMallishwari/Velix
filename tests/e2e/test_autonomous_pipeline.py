"""End-to-End Autonomous Execution Verification."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from velix_agent.core.message import ToolCallPart
from velix_agent.core.response import AgentResponse
from velix_agent.core.runtime import Runtime
from velix_agent.orchestrator.models import OrchestratorState


class FakeProvider:
    def __init__(self, responses: list[AgentResponse]) -> None:
        self.responses = responses
        self.call_count = 0
        self.prompts: list[str] = []

    def generate(self, messages: list[Any], tools: Any = None) -> AgentResponse:
        content = messages[-1].content
        if isinstance(content, list) and len(content) > 0:
            if hasattr(content[0], "text"):
                self.prompts.append(content[0].text)

        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return AgentResponse(status="success", text="fallback")


@patch("velix_agent.providers.factory.get_provider")
def test_e2e_autonomous_pipeline(mock_get_provider: Any, tmp_path: Path, monkeypatch: Any) -> None:
    # 1. Use pytest tmp_path
    # 2. Use monkeypatch.chdir(tmp_path) so the real Runtime operates entirely inside the temporary workspace.
    monkeypatch.chdir(tmp_path)

    # Fake a planner JSON response
    plan_json = json.dumps({
        "goal": "Test E2E",
        "steps": [
            {
                "step_id": "1",
                "title": "Do the thing",
                "description": "Test doing the thing",
                "dependencies": [],
            }
        ]
    })

    # 5. Create a deterministic FakeProvider
    # 6. The FakeProvider must return deterministic responses
    provider = FakeProvider([
        # Response 1: Planner Plan creation
        AgentResponse(status="success", text=f"```json\n{plan_json}\n```"),

        # Response 2: Agent Attempt 1 -> fail intentionally with a real command
        # 9. First execution attempt must intentionally fail through a REAL tool.
        # 10. Prefer a real run_command invocation that produces a deterministic non-zero result.
        AgentResponse(
            text="",
            status="success",
            tool_calls=[ToolCallPart(tool_name="run_command", args={"command": ["sh", "-c", "echo 'command not found' >&2 && exit 1"]}, id="call_1")],
        ),

        # Response 3: Agent Attempt 2 (sees retry_context) -> execute real tool
        # 14. The retry attempt must invoke a REAL write_file tool.
        AgentResponse(
            text="",
            status="success",
            tool_calls=[ToolCallPart(tool_name="write_file", args={"file_path": "success.txt", "content": "fixed"}, id="call_2")],
        ),

        # Response 4: Agent finalization -> "done"
        AgentResponse(status="success", text="done step 1"),
    ])
    mock_get_provider.return_value = provider

    # 7. Use the REAL: Runtime, TaskPlanner, AutonomousCodingLoop, OrchestratorController, CodingAgent, Agent, ToolRegistry, tools, SandboxManager, ResultAnalyzer
    # Create real runtime inside the tmp_path
    runtime = Runtime.create()

    # Run the autonomous loop
    state = runtime.app_loop.run("Write a file, handle failure")


    for p in provider.prompts:
        print("PROMPT:", p)
    print("CALL COUNT:", provider.call_count)
    assert state == OrchestratorState.COMPLETED

    # 15. Verify the file physically exists inside tmp_path
    assert (tmp_path / "success.txt").exists()

    # 16. Verify its exact contents
    assert (tmp_path / "success.txt").read_text() == "fixed"

    # 13. Verify that the retry attempt receives retry_context
    assert len(provider.prompts) > 2
    assert "RETRY CONTEXT:" in provider.prompts[2]

    # 18. Verify at least one actual tool invocation occurred
    # Checked implicitly by file existing

    # 19. Verify at least two TaskStep attempts occurred
    # The first attempt fails, so total_step_attempts reaches at least 2.
    assert provider.call_count == 4

    # 11, 12. Verify that failure travels through ResultAnalyzer -> Orchestrator, starts retry
    # Checked implicitly by the retry prompt injection and state reaching COMPLETED after retry
