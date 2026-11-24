import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiosqlite

from app.config import settings

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id);
"""


@asynccontextmanager
async def get_db(db_path: Optional[str] = None) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager for SQLite database connections."""
    path = db_path if db_path is not None else settings.get_db_path()
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables and indexes on startup."""
    async with get_db(db_path) as db:
        await db.executescript(CREATE_TABLES_SQL)
        await db.commit()


async def check_db_health(db_path: Optional[str] = None) -> bool:
    """Verify database connectivity with a lightweight query."""
    try:
        async with get_db(db_path) as db:
            async with db.execute("SELECT 1") as cursor:
                row = await cursor.fetchone()
                return row is not None and row[0] == 1
    except Exception:
        return False


async def get_session_messages(
    session_id: str, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve stored messages for a session oldest first, without the system prompt.
    Returns empty list if session has no recorded messages.
    """
    async with get_db(db_path) as db:
        query = """
            SELECT role, content, metadata
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
        """
        async with db.execute(query, (session_id,)) as cursor:
            rows = await cursor.fetchall()
            messages: List[Dict[str, Any]] = []
            for row in rows:
                parsed_meta: Optional[Dict[str, Any]] = None
                raw_meta = row["metadata"]
                if raw_meta:
                    try:
                        parsed_meta = json.loads(raw_meta)
                    except json.JSONDecodeError:
                        parsed_meta = None

                item: Dict[str, Any] = {
                    "role": row["role"],
                    "content": row["content"],
                }
                if parsed_meta is not None:
                    item["metadata"] = parsed_meta
                messages.append(item)
            return messages


async def add_message(
    session_id: str,
    role: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> int:
    """
    Store a message into SQLite. Server time is recorded in ISO-8601 UTC format.
    Metadata is serialized to JSON string for assistant messages.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata) if metadata is not None else None

    async with get_db(db_path) as db:
        query = """
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """
        cursor = await db.execute(query, (session_id, role, content, meta_json, now_iso))
        await db.commit()
        return cursor.lastrowid
