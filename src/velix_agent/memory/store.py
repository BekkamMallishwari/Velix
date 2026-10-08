"""Memory store implementation for VelixAgent using SQLite + FTS5."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

# Common secret patterns
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9-_]{20,}"),  # OpenAI
    re.compile(r"gh[po]_[A-Za-z0-9_]{36,}"),  # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]+"),  # GitHub fine-grained
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(r"-----BEGIN .* PRIVATE KEY-----"),  # SSH / Private keys
    re.compile(r"sk_(live|test)_[A-Za-z0-9]+"),  # Stripe keys
]


class MemoryError(Exception):
    """Base class for memory-related errors."""

    pass


class MemoryConfigError(MemoryError):
    """Raised when memory configuration/requirements are invalid."""

    pass


class MemoryValidationError(MemoryError):
    """Raised when memory input fails validation."""

    pass


class MemoryManager:
    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root)
        self.db_path = self.workspace_root / ".velix" / "memory.db"
        self._fts5_supported: bool | None = None

    def _check_fts5_support(self, conn: sqlite3.Connection) -> bool:
        if self._fts5_supported is not None:
            return self._fts5_supported

        try:
            conn.execute("CREATE VIRTUAL TABLE temp.fts5_test USING fts5(col1)")
            conn.execute("DROP TABLE temp.fts5_test")
            self._fts5_supported = True
        except sqlite3.Error:
            self._fts5_supported = False

        return self._fts5_supported

    def _check_secrets(self, text: str) -> None:
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise MemoryValidationError(
                    "Content contains potential secrets which are forbidden."
                )

    def initialize_db(self) -> None:
        """Initialize the database schema if needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                if not self._check_fts5_support(conn):
                    raise MemoryConfigError("SQLite FTS5 extension is not available.")

                # Create main memory table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_type TEXT NOT NULL
                            CHECK(memory_type IN ('project_fact', 'task_hindsight')),
                        topic TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # Create FTS5 virtual table
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                        topic,
                        content,
                        content='memory',
                        content_rowid='id'
                    );
                """)

                # Triggers for syncing FTS
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
                        INSERT INTO memory_fts(rowid, topic, content)
                        VALUES (new.id, new.topic, new.content);
                    END;
                """)

                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, topic, content)
                        VALUES ('delete', old.id, old.topic, old.content);
                    END;
                """)

                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory BEGIN
                        INSERT INTO memory_fts(memory_fts, rowid, topic, content)
                        VALUES ('delete', old.id, old.topic, old.content);
                        INSERT INTO memory_fts(rowid, topic, content)
                        VALUES (new.id, new.topic, new.content);
                    END;
                """)
        except sqlite3.Error as e:
            raise MemoryError(f"Database error during initialization: {e}") from e

    def store(self, memory_type: str, topic: str, content: str) -> int:
        if memory_type not in ("project_fact", "task_hindsight"):
            raise MemoryValidationError(f"Invalid memory_type: {memory_type}")

        if not content or not content.strip():
            raise MemoryValidationError("Content cannot be empty")

        if len(topic) > 100:
            raise MemoryValidationError("Topic exceeds maximum length of 100 characters")

        if len(content) > 2000:
            raise MemoryValidationError("Content exceeds maximum length of 2000 characters")

        self._check_secrets(topic)
        self._check_secrets(content)

        self.initialize_db()

        try:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                # Check maximum rows
                cur = conn.execute("SELECT COUNT(*) FROM memory")
                count = cur.fetchone()[0]

                # Check for duplicates (case-insensitive)
                cur = conn.execute(
                    "SELECT id FROM memory WHERE memory_type = ? "
                    "AND LOWER(topic) = LOWER(?) AND LOWER(content) = LOWER(?)",
                    (memory_type, topic, content),
                )
                row = cur.fetchone()
                if row:
                    return int(row[0])

                if count >= 1000:
                    raise MemoryError("Maximum of 1000 memory rows per workspace reached")

                cur = conn.execute(
                    "INSERT INTO memory (memory_type, topic, content) VALUES (?, ?, ?)",
                    (memory_type, topic, content),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise MemoryError(f"Database error during store: {e}") from e

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        if limit < 1 or limit > 10:
            raise MemoryValidationError(f"Invalid limit: {limit}. Must be between 1 and 10.")

        if not query or not query.strip():
            return []

        # Safe quoting for FTS query
        safe_query = '"' + query.replace('"', '""') + '"'

        try:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                # Use rank ordering for BM25
                cur = conn.execute(
                    """
                    SELECT m.id, m.memory_type, m.topic, m.content, m.created_at
                    FROM memory_fts f
                    JOIN memory m ON f.rowid = m.id
                    WHERE memory_fts MATCH ?
                    ORDER BY f.rank
                    LIMIT ?
                    """,
                    (safe_query, limit),
                )

                results = []
                for row in cur:
                    results.append(
                        {
                            "id": row["id"],
                            "memory_type": row["memory_type"],
                            "topic": row["topic"],
                            "content": row["content"],
                            "created_at": row["created_at"],
                        }
                    )
                return results
        except sqlite3.Error as e:
            raise MemoryError(f"Database error during search: {e}") from e

    def delete(self, memory_id: int) -> bool:
        if not self.db_path.exists():
            return False

        try:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cur = conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
                return cur.rowcount > 0
        except sqlite3.Error as e:
            raise MemoryError(f"Database error during delete: {e}") from e
