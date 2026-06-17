import aiosqlite
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

DB_PATH = os.path.join("data", "chat_monitor.db")


async def init_db() -> None:
    """Initialize database with Business Bot tables."""
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # Business connections table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                business_connection_id TEXT NOT NULL UNIQUE,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                is_enabled BOOLEAN DEFAULT 1,
                connected_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        # Business messages table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS business_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_connection_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                from_user_id INTEGER,
                from_username TEXT,
                text TEXT,
                is_outgoing BOOLEAN DEFAULT 0,
                timestamp TEXT NOT NULL,
                UNIQUE(business_connection_id, message_id)
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_business_messages_connection 
            ON business_messages (business_connection_id, timestamp)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_business_messages_chat 
            ON business_messages (chat_id, timestamp)
        """)

        await db.commit()
    print("Database initialized successfully (Business Bot mode).")


async def save_business_connection(
    user_id: int,
    business_connection_id: str,
    chat_id: int,
    chat_title: str = None
) -> bool:
    """Save or update business connection."""
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO business_connections 
                (user_id, business_connection_id, chat_id, chat_title, connected_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_connection_id) DO UPDATE SET
                    is_enabled = 1,
                    chat_title = COALESCE(?, chat_title),
                    updated_at = ?
                """,
                (user_id, business_connection_id, chat_id, chat_title, now, now, chat_title, now)
            )
            await db.commit()
            return True
        except Exception as e:
            print(f"Error saving business connection: {e}")
            return False


async def disable_business_connection(business_connection_id: str):
    """Disable business connection."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE business_connections SET is_enabled = 0, updated_at = ? WHERE business_connection_id = ?",
            (now, business_connection_id)
        )
        await db.commit()


async def save_business_message(
    business_connection_id: str,
    chat_id: int,
    message_id: int,
    from_user_id: int = None,
    from_username: str = None,
    text: str = None,
    is_outgoing: bool = False,
    timestamp: str = None
):
    """Save business message."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT OR IGNORE INTO business_messages 
                (business_connection_id, chat_id, message_id, from_user_id, from_username, text, is_outgoing, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (business_connection_id, chat_id, message_id, from_user_id, from_username, text, is_outgoing, timestamp)
            )
            await db.commit()
        except Exception as e:
            print(f"Error saving business message: {e}")


async def get_user_business_chats(user_id: int) -> List[Dict[str, Any]]:
    """Get active business chats for user."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM business_connections 
            WHERE user_id = ? AND is_enabled = 1
            ORDER BY connected_at DESC
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_messages_for_analysis(business_connection_id: str, limit: int = 300) -> List[Dict[str, Any]]:
    """Get recent messages for Grok analysis."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM business_messages 
            WHERE business_connection_id = ?
            ORDER BY timestamp DESC 
            LIMIT ?
            """,
            (business_connection_id, limit)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]
