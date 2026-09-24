import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MYHUB_DB_PATH", BASE_DIR / "myhub.db"))


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                url TEXT NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at DESC)"
        )


def upsert_item(item):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO items (
                external_id, source, category, title, summary, url, published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                source=excluded.source,
                category=excluded.category,
                title=excluded.title,
                summary=excluded.summary,
                url=excluded.url,
                published_at=excluded.published_at
            """,
            (
                item["external_id"],
                item["source"],
                item["category"],
                item["title"],
                item.get("summary", ""),
                item["url"],
                item.get("published_at"),
            ),
        )


def get_items(limit=80, category=None):
    init_db()
    query = """
        SELECT source, category, title, summary, url, published_at
        FROM items
    """
    params = []

    if category:
        query += " WHERE lower(category) = lower(?)"
        params.append(category)

    query += " ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?"
    params.append(limit)

    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
