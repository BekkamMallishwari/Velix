import sqlite3
from pathlib import Path
from typing import Any

import pytest

from velix_agent.memory.store import (
    MemoryError,
    MemoryManager,
    MemoryValidationError,
)


@pytest.fixture
def memory(tmp_path: Path) -> MemoryManager:
    return MemoryManager(tmp_path)


def test_database_initialization_and_schema(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    manager.initialize_db()

    assert manager.db_path.exists()

    with sqlite3.connect(manager.db_path) as conn:
        # Check tables exist
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}
        assert "memory" in table_names
        assert "memory_fts" in table_names

        # Check triggers exist
        triggers = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        trigger_names = {t[0] for t in triggers}
        assert "memory_ai" in trigger_names
        assert "memory_ad" in trigger_names
        assert "memory_au" in trigger_names


def test_fts5_availability(memory: MemoryManager) -> None:
    with sqlite3.connect(":memory:") as conn:
        assert memory._check_fts5_support(conn) is True


def test_insert_and_fts_trigger(memory: MemoryManager) -> None:
    mem_id = memory.store("project_fact", "Test Topic", "Test content for FTS.")
    assert mem_id > 0

    with sqlite3.connect(memory.db_path) as conn:
        # Direct check in FTS
        row = conn.execute(
            "SELECT rowid, topic, content FROM memory_fts WHERE rowid = ?", (mem_id,)
        ).fetchone()
        assert row is not None
        assert row[1] == "Test Topic"
        assert row[2] == "Test content for FTS."


def test_search_ranking_bm25(memory: MemoryManager) -> None:
    memory.store("project_fact", "apple", "This is an apple.")
    memory.store("project_fact", "apple multi", "Apple apple apple.")

    results = memory.search("apple")
    assert len(results) == 2
    # Second should rank higher due to more occurrences of 'apple'
    assert results[0]["topic"] == "apple multi"


def test_delete_and_fts_synchronization(memory: MemoryManager) -> None:
    mem_id = memory.store("task_hindsight", "Delete me", "Soon to be gone.")
    results = memory.search("gone")
    assert len(results) == 1

    deleted = memory.delete(mem_id)
    assert deleted is True

    results_after = memory.search("gone")
    assert len(results_after) == 0

    # Check false delete
    assert memory.delete(9999) is False


def test_duplicate_detection(memory: MemoryManager) -> None:
    id1 = memory.store("project_fact", "Dup Topic", "Dup content")
    id2 = memory.store("project_fact", "dup topic", "DUP CONTENT")  # case insensitive
    assert id1 == id2


def test_maximum_1000_rows(memory: MemoryManager) -> None:
    # Mock row count query
    memory.store("project_fact", "Initial", "Data")

    with sqlite3.connect(memory.db_path) as conn:
        # Insert 999 more rows manually to reach 1000
        conn.executemany(
            "INSERT INTO memory (memory_type, topic, content) VALUES (?, ?, ?)",
            [("project_fact", f"Topic {i}", "Content") for i in range(999)],
        )

    with pytest.raises(MemoryError, match="Maximum of 1000 memory rows"):
        memory.store("project_fact", "One too many", "Boom")


def test_validation_topic_length(memory: MemoryManager) -> None:
    long_topic = "A" * 101
    with pytest.raises(MemoryValidationError, match="Topic exceeds maximum length"):
        memory.store("project_fact", long_topic, "Content")


def test_validation_content_length(memory: MemoryManager) -> None:
    long_content = "A" * 2001
    with pytest.raises(MemoryValidationError, match="Content exceeds maximum length"):
        memory.store("project_fact", "Topic", long_content)


def test_empty_content_rejection(memory: MemoryManager) -> None:
    with pytest.raises(MemoryValidationError, match="Content cannot be empty"):
        memory.store("project_fact", "Topic", "   ")


def test_invalid_memory_type_rejection(memory: MemoryManager) -> None:
    with pytest.raises(MemoryValidationError, match="Invalid memory_type"):
        memory.store("invalid_type", "Topic", "Content")


def test_search_limit_validation(memory: MemoryManager) -> None:
    memory.store("project_fact", "A", "Content")

    with pytest.raises(MemoryValidationError, match="Invalid limit"):
        memory.search("Content", limit=0)

    with pytest.raises(MemoryValidationError, match="Invalid limit"):
        memory.search("Content", limit=11)


def test_empty_search(memory: MemoryManager) -> None:
    memory.store("project_fact", "Topic", "Content")
    assert memory.search("") == []
    assert memory.search("   ") == []


def test_search_when_db_does_not_exist(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path)
    assert manager.search("anything") == []


def test_workspace_isolation(tmp_path: Path) -> None:
    ws1 = tmp_path / "ws1"
    ws2 = tmp_path / "ws2"
    m1 = MemoryManager(ws1)
    m2 = MemoryManager(ws2)

    m1.store("project_fact", "Secret1", "Data1")

    assert len(m1.search("Data1")) == 1
    assert len(m2.search("Data1")) == 0


def test_secret_rejection(memory: MemoryManager) -> None:
    secrets = [
        "sk-1234567890abcdefghij1234567890",
        "ghp_1234567890abcdefghij1234567890abcdef",
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN RSA PRIVATE KEY-----",
        "sk_live_1234567890",
    ]
    for secret in secrets:
        with pytest.raises(MemoryValidationError, match="potential secrets"):
            memory.store("project_fact", "Topic", secret)

        with pytest.raises(MemoryValidationError, match="potential secrets"):
            memory.store("project_fact", secret, "Content")


def test_controlled_database_failure_handling(
    memory: MemoryManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory.initialize_db()

    # Force an operational error by renaming the file while connected or similar,
    # or monkeypatching sqlite3.connect
    def mock_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        raise sqlite3.OperationalError("Mocked failure")

    monkeypatch.setattr(sqlite3, "connect", mock_connect)

    with pytest.raises(MemoryError, match=r"Database error during (store|initialization)"):
        memory.store("project_fact", "T", "C")

    with pytest.raises(MemoryError, match="Database error during search"):
        memory.search("T")

    with pytest.raises(MemoryError, match="Database error during delete"):
        memory.delete(1)
