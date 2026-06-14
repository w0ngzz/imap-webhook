from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_messages (
                    mailbox TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uidvalidity TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    message_id TEXT,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (mailbox, folder, uidvalidity, uid)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS folder_state (
                    mailbox TEXT NOT NULL,
                    folder TEXT NOT NULL,
                    uidvalidity TEXT NOT NULL,
                    highest_uid INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (mailbox, folder, uidvalidity)
                )
                """
            )

    def has_processed(self, mailbox: str, folder: str, uidvalidity: str, uid: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT 1 FROM processed_messages
                WHERE mailbox = ? AND folder = ? AND uidvalidity = ? AND uid = ?
                """,
                (mailbox, folder, uidvalidity, uid),
            ).fetchone()
        return row is not None

    def mark_processed(
        self,
        mailbox: str,
        folder: str,
        uidvalidity: str,
        uid: str,
        message_id: str | None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO processed_messages
                    (mailbox, folder, uidvalidity, uid, message_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (mailbox, folder, uidvalidity, uid, message_id),
            )
            self._conn.execute(
                """
                INSERT INTO folder_state (mailbox, folder, uidvalidity, highest_uid)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mailbox, folder, uidvalidity)
                DO UPDATE SET
                    highest_uid = MAX(highest_uid, excluded.highest_uid),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (mailbox, folder, uidvalidity, int(uid)),
            )

    def highest_uid(self, mailbox: str, folder: str, uidvalidity: str) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT highest_uid FROM folder_state
                WHERE mailbox = ? AND folder = ? AND uidvalidity = ?
                """,
                (mailbox, folder, uidvalidity),
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
