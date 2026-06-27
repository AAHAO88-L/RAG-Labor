"""SQLite 数据库统一层 — 用户表 + 对话表"""

import sqlite3
import os
import json
import time
import threading

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
DB_PATH = os.path.join(DB_DIR, "conversations.db")
os.makedirs(DB_DIR, exist_ok=True)

_local = threading.local()


def get_conn():
    """获取当前线程的数据库连接（自动复用）。"""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL DEFAULT '新对话',
            messages TEXT NOT NULL DEFAULT '[]',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
        CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            filename TEXT NOT NULL,
            full_text TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_contracts_user ON contracts(user_id);
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            message_index INTEGER NOT NULL,
            query_text TEXT NOT NULL,
            answer_text TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating IN (1, -1)),
            sources_json TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
    """)
    conn.commit()


# ── 用户操作 ──

def create_user(username, hashed_password):
    conn = get_conn()
    now = time.time()
    try:
        conn.execute(
            "INSERT INTO users (username, hashed_password, display_name, created_at) VALUES (?, ?, ?, ?)",
            (username, hashed_password, username, now),
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
        return user_id
    except sqlite3.IntegrityError:
        return None


def get_user_by_username(username):
    row = get_conn().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    row = get_conn().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def update_user_avatar(user_id, avatar_b64):
    conn = get_conn()
    conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_b64, user_id))
    conn.commit()


def update_user_password(user_id, hashed_password):
    conn = get_conn()
    conn.execute("UPDATE users SET hashed_password = ? WHERE id = ?", (hashed_password, user_id))
    conn.commit()


# ── 对话操作（带用户隔离）──

def list_conversations(user_id, search=None, limit=200, offset=0):
    conn = get_conn()
    if search:
        rows = conn.execute(
            """SELECT id, title, messages, pinned, updated_at FROM conversations
               WHERE user_id = ? AND (title LIKE ? OR messages LIKE ?)
               ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?""",
            (user_id, f"%{search}%", f"%{search}%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, title, messages, pinned, updated_at FROM conversations
               WHERE user_id = ? ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()

    convs = []
    for row in rows:
        msgs = json.loads(row["messages"])
        summary = ""
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
                summary = m["content"][:30]
                if len(m["content"]) > 30:
                    summary += "…"
                break
        convs.append({
            "id": row["id"],
            "title": row["title"],
            "pinned": bool(row["pinned"]),
            "summary": summary or row["title"],
            "mtime": row["updated_at"],
        })
    return convs


def create_conversation(conv_id, user_id):
    conn = get_conn()
    now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO conversations (id, user_id, title, messages, pinned, created_at, updated_at) VALUES (?, ?, '新对话', '[]', 0, ?, ?)",
        (conv_id, user_id, now, now),
    )
    conn.commit()


def save_conversation(conv_id, user_id, title, messages):
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT pinned, title FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
    ).fetchone()
    pinned = 1 if (row and row["pinned"]) else 0
    existing_title = row["title"] if row else None
    if existing_title:
        title = existing_title
    conn.execute(
        """INSERT OR REPLACE INTO conversations (id, user_id, title, messages, pinned, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM conversations WHERE id = ? AND user_id = ?), ?), ?)""",
        (conv_id, user_id, title, json.dumps(messages, ensure_ascii=False), pinned, conv_id, user_id, now, now),
    )
    conn.commit()


def load_conversation(conv_id, user_id):
    row = get_conn().execute(
        "SELECT title, messages FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
    ).fetchone()
    if row:
        return {"title": row["title"], "messages": json.loads(row["messages"])}
    return None


def delete_conversation(conv_id, user_id):
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id))
    conn.commit()


def toggle_pin(conv_id, user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET pinned = ~pinned + 2 WHERE id = ? AND user_id = ?",
        (conv_id, user_id),
    )
    conn.commit()


def rename_conversation(conv_id, user_id, title):
    conn = get_conn()
    conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                 (title, time.time(), conv_id, user_id))
    conn.commit()


# ── 反馈操作 ──

def save_feedback(conversation_id, user_id, message_index, query_text, answer_text, rating, sources_json="", comment=""):
    conn = get_conn()
    now = time.time()
    conn.execute(
        """INSERT INTO feedback (conversation_id, user_id, message_index, query_text, answer_text, rating, sources_json, comment, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (conversation_id, user_id, message_index, query_text, answer_text, rating, sources_json, comment, now),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_feedback_stats():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as total, SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) as thumbs_up, SUM(CASE WHEN rating=-1 THEN 1 ELSE 0 END) as thumbs_down FROM feedback"
    ).fetchone()
    return dict(row) if row else {"total": 0, "thumbs_up": 0, "thumbs_down": 0}


# ── 合同操作 ──

def create_contract(contract_id, user_id, filename, full_text):
    conn = get_conn()
    now = time.time()
    conn.execute(
        "INSERT INTO contracts (id, user_id, filename, full_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (contract_id, user_id, filename, full_text, now),
    )
    conn.commit()


def list_contracts(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename, created_at FROM contracts WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_contract(contract_id, user_id):
    row = get_conn().execute(
        "SELECT * FROM contracts WHERE id = ? AND user_id = ?", (contract_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def delete_contract(contract_id, user_id):
    conn = get_conn()
    conn.execute("DELETE FROM contracts WHERE id = ? AND user_id = ?", (contract_id, user_id))
    conn.commit()
