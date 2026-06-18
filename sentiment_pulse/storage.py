import sqlite3
import json
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple

from .config import DB_PATH, ensure_home, DEFAULT_WATCHLIST, DEFAULT_SYNONYM_GROUPS


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
                negative_posts INTEGER DEFAULT 0,
                avg_sentiment REAL DEFAULT 0,
                alerts_json TEXT,
                top_keywords_json TEXT,
                negative_snippets_json TEXT,
                top_links_json TEXT,
                source_statuses_json TEXT,
                group_alerts_json TEXT,
                watch_mode INTEGER DEFAULT 0,
                session_id INTEGER
            )
        """)
        _migrate_scans_table(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watch_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game TEXT NOT NULL,
                sources TEXT NOT NULL,
                time_range TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                interval_seconds INTEGER DEFAULT 300,
                rounds INTEGER DEFAULT 0,
                notes TEXT
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
            CREATE TABLE IF NOT EXISTS synonym_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT UNIQUE NOT NULL,
                words_json TEXT NOT NULL,
                added_at INTEGER NOT NULL,
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
        _seed_default_synonyms(conn)


def _migrate_scans_table(conn):
    """迁移旧的 scans 表，补齐缺失列"""
    cur = conn.execute("PRAGMA table_info(scans)")
    columns = {row["name"] for row in cur.fetchall()}
    new_columns = [
        ("avg_sentiment", "REAL DEFAULT 0"),
        ("alerts_json", "TEXT"),
        ("top_keywords_json", "TEXT"),
        ("negative_snippets_json", "TEXT"),
        ("top_links_json", "TEXT"),
        ("source_statuses_json", "TEXT"),
        ("group_alerts_json", "TEXT"),
        ("watch_mode", "INTEGER DEFAULT 0"),
        ("session_id", "INTEGER"),
    ]
    for col_name, col_def in new_columns:
        if col_name not in columns:
            try:
                conn.execute(f"ALTER TABLE scans ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass


def _seed_default_watchlist(conn):
    cur = conn.execute("SELECT COUNT(*) as c FROM watchlist")
    if cur.fetchone()["c"] == 0:
        now = int(time.time())
        for kw in DEFAULT_WATCHLIST:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (keyword, added_at, threshold) VALUES (?, ?, ?)",
                (kw, now, 1.5)
            )


def _seed_default_synonyms(conn):
    cur = conn.execute("SELECT COUNT(*) as c FROM synonym_groups")
    if cur.fetchone()["c"] == 0:
        now = int(time.time())
        for g in DEFAULT_SYNONYM_GROUPS:
            conn.execute(
                "INSERT OR IGNORE INTO synonym_groups (label, words_json, added_at) VALUES (?, ?, ?)",
                (g["label"], json.dumps(g["words"], ensure_ascii=False), now)
            )


# ============ 观察会话管理 ============

def start_watch_session(game: str, sources: List[str], time_range: str,
                        interval_seconds: int = 300) -> int:
    """开启一个观察会话，返回 session_id"""
    now = int(time.time())
    sources_key = _sources_key(sources)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO watch_sessions
               (game, sources, time_range, started_at, interval_seconds, rounds)
               VALUES (?, ?, ?, ?, ?, 0)""",
            (game, sources_key, time_range, now, interval_seconds)
        )
        return cur.lastrowid


def end_watch_session(session_id: int, rounds: int = None, notes: str = None) -> bool:
    """结束观察会话"""
    now = int(time.time())
    with get_conn() as conn:
        updates = ["ended_at = ?"]
        params = [now]
        if rounds is not None:
            updates.append("rounds = ?")
            params.append(rounds)
        if notes:
            updates.append("notes = ?")
            params.append(notes)
        params.append(session_id)
        cur = conn.execute(
            f"UPDATE watch_sessions SET {', '.join(updates)} WHERE id = ?",
            tuple(params)
        )
        return cur.rowcount > 0


def list_watch_sessions(limit: int = 20, game: str = None) -> List[Dict]:
    """列出观察会话"""
    with get_conn() as conn:
        sql = "SELECT * FROM watch_sessions"
        params = []
        if game:
            sql += " WHERE game = ?"
            params.append(game)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "game": r["game"],
                "sources": json.loads(r["sources"] or "[]"),
                "time_range": r["time_range"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "interval_seconds": r["interval_seconds"],
                "rounds": r["rounds"] or 0,
                "notes": r["notes"],
            }
            for r in cur.fetchall()
        ]


def get_watch_session(session_id: int) -> Optional[Dict]:
    """获取会话详情"""
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM watch_sessions WHERE id = ?", (session_id,))
        r = cur.fetchone()
        if not r:
            return None
        session = {
            "id": r["id"],
            "game": r["game"],
            "sources": json.loads(r["sources"] or "[]"),
            "time_range": r["time_range"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "interval_seconds": r["interval_seconds"],
            "rounds": r["rounds"] or 0,
            "notes": r["notes"],
        }
        cur2 = conn.execute("SELECT id FROM scans WHERE session_id = ? ORDER BY scanned_at ASC",
                            (session_id,))
        session["scan_ids"] = [row["id"] for row in cur2.fetchall()]
        return session


def list_session_scans(session_id: int) -> List[Dict]:
    """列出某次会话的所有巡检记录（按时间升序）"""
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM scans WHERE session_id = ? ORDER BY scanned_at ASC",
                           (session_id,))
        return [_row_to_scan_dict(r) for r in cur.fetchall()]


def increment_session_rounds(session_id: int) -> bool:
    """会话轮次 +1"""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE watch_sessions SET rounds = rounds + 1 WHERE id = ?",
            (session_id,)
        )
        return cur.rowcount > 0


# ============ 同义词组 ============

def get_synonym_groups(enabled_only: bool = True) -> List[Dict]:
    with get_conn() as conn:
        if enabled_only:
            cur = conn.execute("SELECT * FROM synonym_groups WHERE enabled = 1 ORDER BY id ASC")
        else:
            cur = conn.execute("SELECT * FROM synonym_groups ORDER BY id ASC")
        return [
            {"id": r["id"], "label": r["label"],
             "words": json.loads(r["words_json"] or "[]"),
             "enabled": bool(r["enabled"]),
             "added_at": r["added_at"]}
            for r in cur.fetchall()
        ]


def add_synonym_group(label: str, words: List[str]) -> bool:
    now = int(time.time())
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO synonym_groups (label, words_json, added_at) VALUES (?, ?, ?)",
                (label.strip(), json.dumps(words, ensure_ascii=False), now)
            )
            return True
        except Exception:
            return False


def remove_synonym_group(label: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM synonym_groups WHERE label = ?", (label.strip(),))
        return cur.rowcount > 0


# ============ 巡检记录 ============

def _sources_key(sources: List[str]) -> str:
    return json.dumps(sorted(set(sources)), ensure_ascii=False)


def _row_to_scan_dict(row) -> Dict:
    return {
        "id": row["id"],
        "game": row["game"],
        "sources": json.loads(row["sources"] or "[]"),
        "time_range": row["time_range"],
        "scanned_at": row["scanned_at"],
        "keyword_freq": json.loads(row["keyword_freq"] or "{}"),
        "total_posts": row["total_posts"],
        "negative_posts": row["negative_posts"],
        "avg_sentiment": row["avg_sentiment"],
        "alerts": json.loads(row["alerts_json"] or "[]"),
        "top_keywords": json.loads(row["top_keywords_json"] or "[]"),
        "negative_snippets": json.loads(row["negative_snippets_json"] or "[]"),
        "top_links": json.loads(row["top_links_json"] or "[]"),
        "source_statuses": json.loads(row["source_statuses_json"] or "{}"),
        "group_alerts": json.loads(row["group_alerts_json"] or "[]"),
        "watch_mode": bool(row["watch_mode"]),
        "session_id": row["session_id"],
    }


def save_scan(
    game: str,
    sources: List[str],
    time_range: str,
    keyword_freq: Dict[str, int],
    total_posts: int = 0,
    negative_posts: int = 0,
    avg_sentiment: float = 0.0,
    alerts: List[Dict] = None,
    top_keywords: List[Dict] = None,
    negative_snippets: List[Dict] = None,
    top_links: List[Dict] = None,
    source_statuses: Dict[str, Dict] = None,
    group_alerts: List[Dict] = None,
    watch_mode: bool = False,
    session_id: int = None,
) -> int:
    now = int(time.time())
    sources_key = _sources_key(sources)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO scans
               (game, sources, time_range, scanned_at, keyword_freq, total_posts, negative_posts,
                avg_sentiment, alerts_json, top_keywords_json, negative_snippets_json,
                top_links_json, source_statuses_json, group_alerts_json, watch_mode, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game, sources_key, time_range, now,
             json.dumps(keyword_freq, ensure_ascii=False),
             total_posts, negative_posts, avg_sentiment,
             json.dumps(alerts or [], ensure_ascii=False),
             json.dumps(top_keywords or [], ensure_ascii=False),
             json.dumps(negative_snippets or [], ensure_ascii=False),
             json.dumps(top_links or [], ensure_ascii=False),
             json.dumps(source_statuses or {}, ensure_ascii=False),
             json.dumps(group_alerts or [], ensure_ascii=False),
             1 if watch_mode else 0,
             session_id)
        )
        scan_id = cur.lastrowid
        if session_id:
            conn.execute("UPDATE watch_sessions SET rounds = rounds + 1 WHERE id = ?", (session_id,))
        return scan_id


def get_previous_scan(game: str, sources: List[str], time_range: str) -> Optional[Dict]:
    sources_key = _sources_key(sources)
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT * FROM scans
               WHERE game = ? AND sources = ? AND time_range = ?
               ORDER BY scanned_at DESC LIMIT 1""",
            (game, sources_key, time_range)
        )
        rows = cur.fetchall()
        if not rows:
            return None
        return _row_to_scan_dict(rows[0])


def get_scan_by_id(scan_id: int) -> Optional[Dict]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_scan_dict(row)


def list_scans(
    game: str = None,
    sources: List[str] = None,
    time_range: str = None,
    watch_mode: bool = None,
    session_id: int = None,
    limit: int = 50,
) -> List[Dict]:
    with get_conn() as conn:
        sql = "SELECT * FROM scans WHERE 1=1"
        params = []
        if game:
            sql += " AND game = ?"
            params.append(game)
        if sources:
            sql += " AND sources = ?"
            params.append(_sources_key(sources))
        if time_range:
            sql += " AND time_range = ?"
            params.append(time_range)
        if watch_mode is not None:
            sql += " AND watch_mode = ?"
            params.append(1 if watch_mode else 0)
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY scanned_at DESC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, tuple(params))
        return [
            {
                "id": r["id"],
                "game": r["game"],
                "sources": json.loads(r["sources"] or "[]"),
                "time_range": r["time_range"],
                "scanned_at": r["scanned_at"],
                "total_posts": r["total_posts"],
                "negative_posts": r["negative_posts"],
                "avg_sentiment": r["avg_sentiment"],
                "watch_mode": bool(r["watch_mode"]),
                "session_id": r["session_id"],
            }
            for r in cur.fetchall()
        ]


# ============ 关注清单 ============

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


# ============ 缓存 ============

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
