"""数据库 CRUD 单元测试（使用内存 SQLite）。"""

import pytest
import threading
import database as db


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', ':memory:')
    db._local = threading.local()
    db.init_db()
    yield
    db._local = threading.local()


def test_init_db_creates_tables():
    conn = db.get_conn()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {r[0] for r in tables}
    assert "users" in table_names
    assert "conversations" in table_names
    assert "contracts" in table_names
    assert "feedback" in table_names


def test_create_and_get_user():
    uid = db.create_user("testuser", "hashed_pw_123")
    assert uid is not None
    user = db.get_user_by_id(uid)
    assert user["username"] == "testuser"
    assert user["hashed_password"] == "hashed_pw_123"


def test_create_user_duplicate_returns_none():
    db.create_user("dup", "pw1")
    assert db.create_user("dup", "pw2") is None


def test_get_user_by_username():
    db.create_user("alice", "pw")
    user = db.get_user_by_username("alice")
    assert user is not None
    assert user["username"] == "alice"


def test_create_and_list_conversations():
    uid = db.create_user("u1", "pw")
    cid1 = "conv001"
    cid2 = "conv002"
    db.create_conversation(cid1, uid)
    db.create_conversation(cid2, uid)
    convs = db.list_conversations(uid)
    assert len(convs) == 2
    ids = [c["id"] for c in convs]
    assert cid1 in ids
    assert cid2 in ids


def test_save_and_load_conversation():
    uid = db.create_user("u2", "pw")
    cid = "conv_test"
    msgs = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好"}]
    db.save_conversation(cid, uid, "测试对话", msgs)
    data = db.load_conversation(cid, uid)
    assert data is not None
    assert data["title"] == "测试对话"
    assert len(data["messages"]) == 2


def test_save_conversation_preserves_title_on_update():
    uid = db.create_user("u3", "pw")
    cid = "conv_keep_title"
    msgs1 = [{"role": "user", "content": "q1"}]
    db.save_conversation(cid, uid, "原始标题", msgs1)
    msgs2 = [{"role": "user", "content": "q2"}]
    db.save_conversation(cid, uid, "新标题", msgs2)
    data = db.load_conversation(cid, uid)
    assert data["title"] == "原始标题"
    assert len(data["messages"]) == 1


def test_delete_conversation():
    uid = db.create_user("u4", "pw")
    cid = "conv_del"
    db.create_conversation(cid, uid)
    db.delete_conversation(cid, uid)
    data = db.load_conversation(cid, uid)
    assert data is None


def test_toggle_pin():
    uid = db.create_user("u5", "pw")
    cid = "conv_pin"
    db.create_conversation(cid, uid)
    db.toggle_pin(cid, uid)
    convs = db.list_conversations(uid)
    assert convs[0]["pinned"] is True
    db.toggle_pin(cid, uid)
    convs = db.list_conversations(uid)
    assert convs[0]["pinned"] is False


def test_feedback_crud():
    uid = db.create_user("u6", "pw")
    fid = db.save_feedback(
        conversation_id="conv_fb",
        user_id=uid,
        message_index=0,
        query_text="问题",
        answer_text="答案",
        rating=1,
    )
    assert fid is not None
    stats = db.get_feedback_stats()
    assert stats["total"] == 1
    assert stats["thumbs_up"] == 1
    assert stats["thumbs_down"] == 0


def test_create_and_list_contracts():
    uid = db.create_user("u7", "pw")
    cid = "contract_test"
    db.create_contract(cid, uid, "合同.docx", "全文内容")
    contracts = db.list_contracts(uid)
    assert len(contracts) == 1
    assert contracts[0]["filename"] == "合同.docx"
