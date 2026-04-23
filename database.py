"""
database.py
-----------
SQLite 数据库模块 — 记录所有对话消息。
"""

import os
import sqlite3
from datetime import datetime
from threading import Lock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "messages.db")

_db_lock = Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id INTEGER,
            ts TEXT NOT NULL,
            direction TEXT NOT NULL,
            sender TEXT NOT NULL,
            session_key TEXT NOT NULL,
            conversation_type TEXT NOT NULL,
            msg_type TEXT NOT NULL,
            text TEXT,
            file_url TEXT,
            duration INTEGER,
            need_auto_reply INTEGER DEFAULT 0,
            auto_reply_completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_session ON messages(session_key)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_created ON messages(created_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_auto_reply ON messages(need_auto_reply, auto_reply_completed, session_key)
    """)
    conn.commit()


def save_message(msg: dict):
    with _db_lock:
        conn = _get_conn()
        conn.execute("""
            INSERT INTO messages (msg_id, ts, direction, sender, session_key,
                                   conversation_type, msg_type, text, file_url, duration,
                                   need_auto_reply, auto_reply_completed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg.get("id"),
            msg.get("ts", ""),
            msg.get("direction", ""),
            msg.get("sender", ""),
            msg.get("session_key", ""),
            msg.get("conversation_type", ""),
            msg.get("msg_type", "text"),
            msg.get("text", ""),
            msg.get("file_url"),
            msg.get("duration"),
            msg.get("need_auto_reply", 0),
            msg.get("auto_reply_completed", 0),
        ))
        conn.commit()


def get_history(since_id: int = 0, limit: int = 200) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT msg_id, ts, direction, sender, session_key,
               conversation_type, msg_type, text, file_url, duration
        FROM messages
        WHERE id > ?
        ORDER BY id ASC
        LIMIT ?
    """, (since_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_sessions(page: int = 1, page_size: int = 50) -> list[dict]:
    conn = _get_conn()
    offset = (page - 1) * page_size
    rows = conn.execute("""
        SELECT session_key, sender, conversation_type,
               MAX(created_at) as last_time,
               COUNT(*) as msg_count
        FROM messages
        GROUP BY session_key
        ORDER BY last_time DESC
        LIMIT ? OFFSET ?
    """, (page_size, offset)).fetchall()
    return [dict(r) for r in rows]


def get_session_messages(session_key: str, limit: int = 200) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT msg_id, ts, direction, sender, session_key,
               conversation_type, msg_type, text, file_url, duration
        FROM messages
        WHERE session_key = ?
        ORDER BY id ASC
        LIMIT ?
    """, (session_key, limit)).fetchall()
    return [dict(r) for r in rows]


def get_pending_auto_reply() -> dict[str, list[dict]]:
    """获取需要自动回复的消息，按 session_key 分组"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT id, msg_id, ts, direction, sender, session_key,
               conversation_type, msg_type, text, file_url, duration
        FROM messages
        WHERE need_auto_reply = 1 AND auto_reply_completed = 0 AND direction = 'in'
        ORDER BY id ASC
    """).fetchall()
    grouped = {}
    for r in rows:
        msg = dict(r)
        session_key = msg["session_key"]
        if session_key not in grouped:
            grouped[session_key] = []
        grouped[session_key].append(msg)
    return grouped


def mark_auto_reply_completed_by_ids(message_ids: list[int]):
    """标记指定id的消息自动回复为已完成"""
    if not message_ids:
        return
    with _db_lock:
        conn = _get_conn()
        placeholders = ",".join(["?"] * len(message_ids))
        conn.execute(f"""
            UPDATE messages
            SET auto_reply_completed = 1
            WHERE id IN ({placeholders}) AND need_auto_reply = 1 AND auto_reply_completed = 0 AND direction = 'in'
        """, message_ids)
        conn.commit()