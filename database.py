"""SQLite 数据库统一层 — 用户表 + 对话表"""

import sqlite3
import os
import json
import time

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conversations")
DB_PATH = os.path.join(DB_DIR, "conversations.db")
os.makedirs(DB_DIR, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            display_name TEXT DEFAULT '',
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
    """)
    conn.commit()
    conn.close()


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
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_user_by_id(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


# ── 对话操作（带用户隔离）──

def list_conversations(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, messages, pinned, updated_at FROM conversations WHERE user_id = ? ORDER BY pinned DESC, updated_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()

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
    conn.close()


def save_conversation(conv_id, user_id, title, messages):
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT pinned FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
    ).fetchone()
    pinned = 1 if (row and row["pinned"]) else 0
    conn.execute(
        """INSERT OR REPLACE INTO conversations (id, user_id, title, messages, pinned, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM conversations WHERE id = ? AND user_id = ?), ?), ?)""",
        (conv_id, user_id, title, json.dumps(messages, ensure_ascii=False), pinned, conv_id, user_id, now, now),
    )
    conn.commit()
    conn.close()


def load_conversation(conv_id, user_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT title, messages FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
    ).fetchone()
    conn.close()
    if row:
        return {"title": row["title"], "messages": json.loads(row["messages"])}
    return None


def delete_conversation(conv_id, user_id):
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id))
    conn.commit()
    conn.close()


def toggle_pin(conv_id, user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET pinned = ~pinned + 2 WHERE id = ? AND user_id = ?",
        (conv_id, user_id),
    )
    conn.commit()
    conn.close()


def rename_conversation(conv_id, user_id, title):
    conn = get_conn()
    conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                 (title, time.time(), conv_id, user_id))
    conn.commit()
    conn.close()
