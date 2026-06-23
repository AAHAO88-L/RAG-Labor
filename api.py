"""FastAPI 应用 — 对话 CRUD + RAG 流式查询 + 用户认证"""

import uuid
import json
import time
import os
import logging

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import database as db
from auth import hash_password, verify_password, create_access_token, get_current_user

logger = logging.getLogger(__name__)

app = FastAPI(title="RAG-Labor API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://127.0.0.1:7860").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求/响应模型 ──

class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class SaveConversationRequest(BaseModel):
    conv_id: str
    title: str
    messages: list


class QueryRequest(BaseModel):
    conv_id: str
    message: str
    history: list = []


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangeAvatarRequest(BaseModel):
    avatar_base64: str


# ── 用户认证 API ──

@app.post("/api/register")
def register(req: RegisterRequest):
    if len(req.username) < 2 or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="用户名至少2位，密码至少4位")
    existing = db.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    hashed = hash_password(req.password)
    user_id = db.create_user(req.username, hashed)
    if user_id is None:
        raise HTTPException(status_code=400, detail="注册失败")
    token = create_access_token({"user_id": user_id, "username": req.username})
    return {"token": token, "user_id": user_id, "username": req.username}


@app.post("/api/login")
def login(req: LoginRequest):
    user = db.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token({"user_id": user["id"], "username": user["username"]})
    return {"token": token, "user_id": user["id"], "username": user["username"]}


@app.get("/api/me")
def get_me(user: dict = Depends(get_current_user)):
    return {
        "user_id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name", ""),
        "avatar": user.get("avatar", ""),
    }


@app.post("/api/change-password")
def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if not verify_password(req.old_password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码至少4位")
    db.update_user_password(user["id"], hash_password(req.new_password))
    return {"ok": True}


@app.post("/api/change-avatar")
def change_avatar(req: ChangeAvatarRequest, user: dict = Depends(get_current_user)):
    db.update_user_avatar(user["id"], req.avatar_base64)
    return {"ok": True}


# ── 对话 API（用户隔离） ──

@app.post("/api/conversations")
def new_conversation(user: dict = Depends(get_current_user)):
    conv_id = uuid.uuid4().hex[:12]
    db.create_conversation(conv_id, user["id"])
    return {"conv_id": conv_id}


@app.get("/api/conversations")
def list_conv(
    user: dict = Depends(get_current_user),
    search: str = Query(default=""),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    return db.list_conversations(user["id"], search=search or None, limit=limit, offset=offset)


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str, user: dict = Depends(get_current_user)):
    data = db.load_conversation(conv_id, user["id"])
    if data is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return data


@app.put("/api/conversations/{conv_id}")
def update_conversation(conv_id: str, req: SaveConversationRequest, user: dict = Depends(get_current_user)):
    db.save_conversation(conv_id, user["id"], req.title, req.messages)
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}")
def delete_conv(conv_id: str, user: dict = Depends(get_current_user)):
    db.delete_conversation(conv_id, user["id"])
    return {"ok": True}


@app.patch("/api/conversations/{conv_id}/pin")
def pin_conv(conv_id: str, user: dict = Depends(get_current_user)):
    db.toggle_pin(conv_id, user["id"])
    return {"ok": True}


# ── RAG 流式查询（SSE） ──

@app.post("/api/query")
def stream_query(req: QueryRequest, user: dict = Depends(get_current_user)):
    from main import multi_retrieve, build_messages
    from models import llm

    message = req.message
    conv_id = req.conv_id

    try:
        contexts = multi_retrieve(message)
    except Exception as e:
        logger.warning("检索失败", exc_info=True)
        return StreamingResponse(_error_stream(f"❌ 检索失败：{e}"), media_type="text/event-stream")

    min_dist = min((c.get("distance", 9999) for c in contexts), default=9999)
    low_confidence = min_dist > 400 or len(contexts) == 0
    msgs = build_messages(req.history, contexts, message)

    async def generate():
        full_answer = ""
        try:
            for chunk in llm.generate_stream(msgs):
                full_answer += chunk
                yield f"data: {json.dumps({'token': chunk, 'done': False}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning("LLM 生成失败", exc_info=True)
            yield f"data: {json.dumps({'token': '', 'error': f'❌ API 调用失败：{e}', 'done': True}, ensure_ascii=False)}\n\n"
            return

        # 保存对话（首次保存时用第一条消息作为标题，后续保持原标题）
        try:
            chat_history = [{"role": "user", "content": message}, {"role": "assistant", "content": full_answer}]
            db.save_conversation(conv_id, user["id"], message, chat_history)
        except Exception:
            logger.warning("保存对话失败", exc_info=True)

        done_payload = {"done": True}
        if low_confidence:
            done_payload["low_confidence"] = True
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


def _error_stream(msg: str):
    import asyncio
    async def gen():
        yield f"data: {json.dumps({'token': msg, 'done': False})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        await asyncio.sleep(0)
    return gen()


# ── 生命周期 ──

@app.on_event("startup")
def startup():
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    logger.info("[OK] 数据库初始化完成")

    try:
        from main import load_index
        load_index()
        logger.info("[OK] ChromaDB 索引加载成功")
    except FileNotFoundError:
        logger.warning("[WARN] ChromaDB 索引不存在，请运行 ingest.py 构建索引")
    except Exception as e:
        logger.warning(f"[WARN] 索引加载异常：{e}")

    try:
        from models.embeddings import get_tokenizer_and_model
        get_tokenizer_and_model()
        logger.info("[OK] BGE 模型预热完成")
    except Exception as e:
        logger.warning(f"[WARN] BGE 模型预热异常：{e}")
