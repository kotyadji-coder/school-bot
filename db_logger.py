import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "logs.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp  TEXT    NOT NULL,
                level      TEXT    NOT NULL,
                message    TEXT    NOT NULL,
                user_id    TEXT,
                action     TEXT,
                channel_id TEXT
            )
            """
        )
        existing = {
            row[1]
            for row in _local.conn.execute("PRAGMA table_info(logs)").fetchall()
        }
        if "channel_id" not in existing:
            _local.conn.execute("ALTER TABLE logs ADD COLUMN channel_id TEXT")
        _local.conn.commit()
    return _local.conn


def log(level: str, action: str, message: str, user_id: str | None = None, channel_id: str | None = None) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO logs (timestamp, level, message, user_id, action, channel_id) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.utcnow().isoformat(sep=" ", timespec="seconds"), level, message, user_id, action, channel_id),
    )
    conn.commit()


def get_recent_logs(limit: int = 100) -> list[sqlite3.Row]:
    conn = _get_conn()
    return conn.execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_stats_today() -> dict:
    conn = _get_conn()
    today = date.today().isoformat()
    explanations = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE action = 'EXPLANATION_DONE' AND timestamp LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]
    errors = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE level = 'ERROR' AND timestamp LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]
    last_error = conn.execute(
        "SELECT message, timestamp FROM logs WHERE level = 'ERROR' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "explanations_today": explanations,
        "errors_today": errors,
        "last_error": dict(last_error) if last_error else None,
    }
