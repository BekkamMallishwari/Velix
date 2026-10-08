from pathlib import Path

import pytest

from velix_agent.memory.store import MemoryManager
from velix_agent.tools.delete_memory import DeleteMemoryTool
from velix_agent.tools.search_memory import SearchMemoryTool
from velix_agent.tools.store_memory import StoreMemoryTool


@pytest.fixture
def memory_manager(tmp_path: Path) -> MemoryManager:
    mm = MemoryManager(workspace_root=tmp_path)
    mm.initialize_db()
    return mm


def test_store_memory_tool(memory_manager: MemoryManager) -> None:
    tool = StoreMemoryTool(memory_manager)

    # Missing args
    res = tool.execute(memory_type="project_fact", topic="topic")
    assert res.status == "error"

    # Valid
    res = tool.execute(memory_type="project_fact", topic="Test Topic", content="Test Content")
    assert res.status == "success"
    assert "id" in res.data

    # Invalid memory type
    res = tool.execute(memory_type="invalid_type", topic="T", content="C")
    assert res.status == "error"
    assert "Invalid memory_type" in res.error

    # Validation (e.g. secret)
    res = tool.execute(
        memory_type="project_fact", topic="secret", content="sk-12345678901234567890"
    )
    assert res.status == "error"
    assert "potential secrets" in res.error


def test_search_memory_tool(memory_manager: MemoryManager) -> None:
    tool = SearchMemoryTool(memory_manager)
    memory_manager.store("project_fact", "Test Topic", "Test Content")

    # Valid
    res = tool.execute(query="Test")
    assert res.status == "success"
    assert len(res.data["results"]) == 1
    assert res.data["results"][0]["topic"] == "Test Topic"

    # Invalid args
    res = tool.execute(query="")
    assert res.status == "error"

    # Bounded results
    for i in range(15):
        memory_manager.store("project_fact", f"Test {i}", "Content")
    res = tool.execute(query="Test")
    assert res.status == "success"
    assert len(res.data["results"]) == 5  # default limit


def test_delete_memory_tool(memory_manager: MemoryManager) -> None:
    mem_id = memory_manager.store("project_fact", "Delete Me", "Content")
    tool = DeleteMemoryTool(memory_manager)

    # Valid
    res = tool.execute(memory_id=mem_id)
    assert res.status == "success"
    assert res.data["deleted"] is True

    # Invalid args
    res = tool.execute()
    assert res.status == "error"

    # Not found
    res = tool.execute(memory_id=999)
    assert res.status == "error"
