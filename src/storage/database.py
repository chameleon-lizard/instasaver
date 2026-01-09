import logging
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass

DB_PATH = Path("data/bridge.db")
logger = logging.getLogger(__name__)


@dataclass
class MessageMapping:
    tg_message_id: int
    tg_chat_id: int
    ig_thread_id: str
    ig_item_id: str
    ig_sender: str | None = None


class Database:
    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        db_existed = DB_PATH.exists()
        self._init_db()

        # Log database status on startup
        with self._conn() as conn:
            seen_count = conn.execute("SELECT COUNT(*) FROM seen_messages").fetchone()[0]
            mapping_count = conn.execute("SELECT COUNT(*) FROM message_mapping").fetchone()[0]

        logger.info(
            "Database initialized: path=%s, existed=%s, seen_messages=%d, mappings=%d",
            DB_PATH.resolve(), db_existed, seen_count, mapping_count
        )

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS message_mapping (
                    id INTEGER PRIMARY KEY,
                    tg_message_id INTEGER NOT NULL,
                    tg_chat_id INTEGER NOT NULL,
                    ig_thread_id TEXT NOT NULL,
                    ig_item_id TEXT NOT NULL,
                    ig_sender TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tg_message_id, tg_chat_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tg_msg
                    ON message_mapping(tg_message_id, tg_chat_id);

                CREATE TABLE IF NOT EXISTS seen_messages (
                    ig_item_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def is_seen(self, ig_item_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_messages WHERE ig_item_id = ?",
                (ig_item_id,)
            ).fetchone()
            return row is not None

    def mark_seen(self, ig_item_id: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_messages (ig_item_id) VALUES (?)",
                (ig_item_id,)
            )

    def save_mapping(self, mapping: MessageMapping):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO message_mapping
                (tg_message_id, tg_chat_id, ig_thread_id, ig_item_id, ig_sender)
                VALUES (?, ?, ?, ?, ?)
            """, (
                mapping.tg_message_id, mapping.tg_chat_id,
                mapping.ig_thread_id, mapping.ig_item_id, mapping.ig_sender
            ))

    def get_mapping_by_tg(self, tg_message_id: int, tg_chat_id: int) -> MessageMapping | None:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM message_mapping
                WHERE tg_message_id = ? AND tg_chat_id = ?
            """, (tg_message_id, tg_chat_id)).fetchone()
            if row:
                return MessageMapping(
                    tg_message_id=row["tg_message_id"],
                    tg_chat_id=row["tg_chat_id"],
                    ig_thread_id=row["ig_thread_id"],
                    ig_item_id=row["ig_item_id"],
                    ig_sender=row["ig_sender"]
                )
            return None
