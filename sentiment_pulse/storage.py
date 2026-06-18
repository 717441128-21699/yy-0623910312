import sqlite3
import json
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple

from .config import DB_PATH, ensure_home, DEFAULT_WATCHLIST


@contextmanager
def get_conn():
    ensure_home()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game TEXT NOT NULL,
                sources TEXT NOT NULL,
                time_range TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                keyword_freq TEXT,
                total_posts INTEGER DEFAULT 0,
                negative_posts INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT UNIQUE NOT NULL,
                added_at INTEGER NOT NULL,
                threshold REAL DEFAULT 1.5,
                enabled INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cached_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game TEXT NOT NULL,
                source TEXT NOT NULL,
                post_id TEXT,
                content TEXT NOT NULL,
                author TEXT,
                url TEXT,
                sentiment REAL,
                created_at INTEGER,
                scanned_at INTEGER NOT NULL,
                UNIQUE(game, source, post_id)
            )
        """)
        _seed_default_watchlist(conn)


def _seed_default_watchlist(conn):
    cur = conn.execute("SELECT COUNT(*) as c FROM watchlist")
    if cur.fetchone()["c"] == 0:
        now = int(time.time())
        for kw in DEFAULT_WATCHLIST:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (keyword, added_at) VALUES (?, ?)",
                (kw, now)
            )


def save_scan(
    game: str,
    sources: List[str],
    time_range: str,
    keyword_freq: Dict[str, int],
    total_posts: int = 0,
    negative_posts: int = 0,
) -> int:
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO scans (game, sources, time_range, scanned_at, keyword_freq, total_posts, negative_posts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (game, json.dumps(sources, ensure_ascii=False), time_range, now,
             json.dumps(keyword_freq, ensure_ascii=False), total_posts, negative_posts)
        )
        return cur.lastrowid


def get_previous_scan(game: str, sources: List[str], time_range: str) -> Optional[Dict]:
    sources_key = json.dumps(sources, ensure_ascii=False)
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT * FROM scans
               WHERE game = ? AND sources = ? AND time_range = ?
               ORDER BY scanned_at DESC LIMIT 2""",
            (game, sources_key, time_range)
        )
        rows = cur.fetchall()
        if len(rows) >= 2:
            row = rows[1]
        elif len(rows) == 1:
            return None
        else:
            return None
        return {
            "id": row["id"],
            "scanned_at": row["scanned_at"],
            "keyword_freq": json.loads(row["keyword_freq"] or "{}"),
            "total_posts": row["total_posts"],
            "negative_posts": row["negative_posts"],
        }


def get_watchlist(enabled_only: bool = True) -> List[Dict]:
    with get_conn() as conn:
        if enabled_only:
            cur = conn.execute("SELECT * FROM watchlist WHERE enabled = 1 ORDER BY added_at ASC")
        else:
            cur = conn.execute("SELECT * FROM watchlist ORDER BY added_at ASC")
        return [
            {"id": r["id"], "keyword": r["keyword"], "added_at": r["added_at"],
             "threshold": r["threshold"], "enabled": bool(r["enabled"])}
            for r in cur.fetchall()
        ]


def add_watch_keyword(keyword: str, threshold: float = 1.5) -> bool:
    now = int(time.time())
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (keyword, added_at, threshold) VALUES (?, ?, ?)",
                (keyword.strip(), now, threshold)
            )
            return True
        except Exception:
            return False


def remove_watch_keyword(keyword: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE keyword = ?", (keyword.strip(),))
        return cur.rowcount > 0


def toggle_watch_keyword(keyword: str, enabled: bool) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE watchlist SET enabled = ? WHERE keyword = ?",
            (1 if enabled else 0, keyword.strip())
        )
        return cur.rowcount > 0


def save_cached_posts(game: str, posts: List[Dict]):
    now = int(time.time())
    with get_conn() as conn:
        for p in posts:
            conn.execute(
                """INSERT OR REPLACE INTO cached_posts
                   (game, source, post_id, content, author, url, sentiment, created_at, scanned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game, p.get("source", "unknown"), p.get("post_id", ""),
                 p.get("content", ""), p.get("author", ""), p.get("url", ""),
                 p.get("sentiment", 0.0), p.get("created_at", now), now)
            )


def get_recent_posts(game: str, since_ts: int) -> List[Dict]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM cached_posts WHERE game = ? AND scanned_at >= ? ORDER BY scanned_at DESC",
            (game, since_ts)
        )
        return [
            {"source": r["source"], "content": r["content"], "author": r["author"],
             "url": r["url"], "sentiment": r["sentiment"], "created_at": r["created_at"]}
            for r in cur.fetchall()
        ]
