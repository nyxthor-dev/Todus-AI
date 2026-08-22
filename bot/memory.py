"""
Memoria persistente por usuario usando SQLite.

Mantiene el historial de conversacion (user/assistant) por cada JID
(telefono en privado, grupo+usuario en grupos).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from .config import settings, PROJECT_ROOT


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,           -- 'private:<phone>' o 'group:<gid>:<phone>'
    role        TEXT NOT NULL,           -- 'user' | 'assistant' | 'system'
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS user_meta (
    phone       TEXT PRIMARY KEY,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    notes       TEXT DEFAULT ''
);
"""


class Memory:
    """Acceso thread-safe al historial de conversacion."""

    def __init__(self, db_path=None):
        path = str(db_path or settings.memory_db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            finally:
                cur.close()

    # --- API publica ---

    @staticmethod
    def session_id_for_private(phone: str) -> str:
        return f"private:{phone}"

    @staticmethod
    def session_id_for_group(group_id: str, phone: str) -> str:
        return f"group:{group_id}:{phone}"

    def add_message(self, session_id: str, role: str, content: str) -> None:
        assert role in {"user", "assistant", "system"}, f"rol invalido: {role}"
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
                (session_id, role, content, time.time()),
            )

    def get_history(self, session_id: str, limit: int | None = None) -> list[dict]:
        limit = limit or settings.memory_max_messages
        with self._cursor() as cur:
            cur.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            )
            rows = cur.fetchall()
        # Invertir para tener orden cronologico (mas viejo -> mas nuevo)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def reset_session(self, session_id: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            return cur.rowcount

    def touch_user(self, phone: str) -> None:
        now = time.time()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO user_meta (phone, first_seen, last_seen, notes) "
                "VALUES (?,?,?, '') "
                "ON CONFLICT(phone) DO UPDATE SET last_seen = excluded.last_seen",
                (phone, now, now),
            )

    def user_stats(self, phone: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT first_seen, last_seen, notes FROM user_meta WHERE phone = ?",
                (phone,),
            )
            r = cur.fetchone()
        if not r:
            return None
        return {"first_seen": r["first_seen"], "last_seen": r["last_seen"], "notes": r["notes"]}

    def trim_session(self, session_id: str, keep: int | None = None) -> int:
        """Mantiene solo los ultimos `keep` mensajes de una sesion."""
        keep = keep or settings.memory_max_messages
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM messages WHERE session_id = ? AND id NOT IN ("
                "  SELECT id FROM messages WHERE session_id = ? "
                "  ORDER BY id DESC LIMIT ?"
                ")",
                (session_id, session_id, keep),
            )
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
