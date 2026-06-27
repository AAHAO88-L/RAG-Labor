"""FastAPI 应用 — 对话 CRUD + RAG 流式查询 + 用户认证"""

import uuid
import json
import time
import os
import logging
import threading

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, status, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import database as db
from auth import hash_password, verify_password, create_access_token, get_current_user
from utils.timing import init_request_timings, get_timings, log_timings

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
    contract_id: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangeAvatarRequest(BaseModel):
    avatar_base64: str


class FeedbackRequest(BaseModel):
    conversation_id: str
    message_index: int
    query_text: str
    answer_text: str
    rating: int  # 1 or -1
    sources_json: str = ""
    comment: str = ""


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


# ── 反馈 API ──

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest, user: dict = Depends(get_current_user)):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=400, detail="rating must be 1 (up) or -1 (down)")
    feedback_id = db.save_feedback(
        conversation_id=req.conversation_id,
        user_id=user["id"],
        message_index=req.message_index,
        query_text=req.query_text,
        answer_text=req.answer_text,
        rating=req.rating,
        sources_json=req.sources_json,
        comment=req.comment,
    )
    logger.info("[feedback] user=%s conv=%s rating=%d id=%d", user["id"], req.conversation_id, req.rating, feedback_id)
    return {"ok": True, "feedback_id": feedback_id}


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


# ── 文档源缓存（避免反复全量扫描 ChromaDB）──

_doc_source_cache = None
_doc_cache_lock = threading.Lock()

def _invalidate_doc_cache():
    global _doc_source_cache
    _doc_source_cache = None

def _refresh_doc_cache():
    global _doc_source_cache
    if _doc_source_cache is not None:
        return
    from main import load_index
    collection = load_index()
    all_data = collection.get(include=["metadatas"])
    seen = set()
    docs = []
    for m in all_data.get("metadatas", []):
        src = m.get("source", "")
        if src and src not in seen:
            seen.add(src)
            docs.append({"path": src, "name": os.path.basename(src)})
    _doc_source_cache = docs


@app.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user)):
    """列出已索引的法律文件（从缓存读取，首次访问时构建）。"""
    with _doc_cache_lock:
        try:
            _refresh_doc_cache()
            return {"documents": _doc_source_cache}
        except Exception as e:
            logger.warning(f"获取文档列表失败: {e}")
            return {"documents": []}



@app.delete("/api/documents")
def delete_document(path: str = Query(...), user: dict = Depends(get_current_user)):
    """从索引中删除指定文件。"""
    from ingest import remove_document
    try:
        count = remove_document(path)
        _invalidate_doc_cache()
        logger.info("删除了 %s (%d 片段)", path, count)
        return {"path": path, "deleted": count, "ok": True}
    except Exception as e:
        logger.error("删除失败: %s", e)
        raise HTTPException(status_code=400, detail=f"删除失败：{e}")


# ── 合同管理 API ──

@app.post("/api/contracts/upload")
async def upload_contract(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """上传合同文件，解析全文后存入 contracts 表"""
    from utils.file_loader import load_file
    import tempfile

    ALLOWED_EXT = {'.pdf', '.docx', '.txt', '.md'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，仅支持 PDF/DOCX/TXT/MD")

    # 保存到临时文件，用 file_loader 解析
    tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"contract_{uuid.uuid4().hex}{ext}")

    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        full_text = load_file(tmp_path)
        if not full_text.strip():
            raise HTTPException(status_code=400, detail="文件内容为空")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"合同解析失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文件解析失败：{e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    contract_id = uuid.uuid4().hex[:12]
    db.create_contract(contract_id, user["id"], file.filename, full_text)
    logger.info("[OK] 合同上传: %s (%d 字符)", file.filename, len(full_text))
    return {"id": contract_id, "filename": file.filename, "chars": len(full_text), "ok": True}


@app.get("/api/contracts")
def list_contracts(user: dict = Depends(get_current_user)):
    """列出当前用户的合同列表。"""
    contracts = db.list_contracts(user["id"])
    return {"contracts": contracts}


@app.get("/api/contracts/{contract_id}")
def get_contract(contract_id: str, user: dict = Depends(get_current_user)):
    """获取单个合同详情（含全文）。"""
    contract = db.get_contract(contract_id, user["id"])
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return contract


@app.delete("/api/contracts/{contract_id}")
def delete_contract(contract_id: str, user: dict = Depends(get_current_user)):
    """删除合同。"""
    db.delete_contract(contract_id, user["id"])
    return {"ok": True}


# ── RAG 流式查询（SSE） ──

_model_ready = False


@app.get("/api/health")
def health():
    """服务健康检查，返回模型就绪状态。"""
    return {"status": "ok", "model_ready": _model_ready}


@app.post("/api/upload-doc")
async def upload_document(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """上传法律文件（PDF/DOCX/TXT/MD/ZIP），解析后增量更新 ChromaDB 索引。"""
    from ingest import add_document, add_documents

    # 限制上传大小 100MB
    MAX_SIZE = 100 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="文件过大，上限为 100MB")

    ALLOWED_EXT = {'.pdf', '.docx', '.txt', '.md'}
    ext = os.path.splitext(file.filename)[1].lower()

    if ext == '.zip':
        import zipfile
        import io
        upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", uuid.uuid4().hex)
        os.makedirs(upload_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                filepaths = []
                source_names = []
                for name in zf.namelist():
                    file_ext = os.path.splitext(name)[1].lower()
                    if file_ext not in ALLOWED_EXT:
                        continue
                    # 只取文件名部分防路径穿越
                    safe_name = os.path.basename(name)
                    if not safe_name:
                        continue
                    tmp_path = os.path.join(upload_dir, safe_name)
                    with open(tmp_path, "wb") as f:
                        f.write(zf.read(name))
                    filepaths.append(tmp_path)
                    source_names.append(os.path.join("data", "uploads", safe_name))
            if not filepaths:
                raise HTTPException(status_code=400, detail="ZIP 中未找到支持的文件格式")
            total = add_documents(filepaths, source_names)
        finally:
            import shutil
            shutil.rmtree(upload_dir, ignore_errors=True)
        _invalidate_doc_cache()
        return {"filename": file.filename, "files": len(filepaths), "chunks": total, "ok": True}

    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，仅支持 PDF/DOCX/TXT/MD/ZIP")

    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    tmp_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")

    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        # 使用原始文件名作为 source，确保 cleanup 和删除能正确匹配
        source = os.path.join("data", "uploads", file.filename)
        chunk_count = add_document(tmp_path, source_override=source)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        logger.error(f"文件处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"文件处理失败：{e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    _invalidate_doc_cache()
    return {"filename": file.filename, "chunks": chunk_count, "ok": True}


@app.post("/api/query")
async def stream_query(req: QueryRequest, request: Request, user: dict = Depends(get_current_user)):
    from main import multi_retrieve, build_messages, retrieve_laws_for_contract, build_review_messages
    from models import llm

    request_id = uuid.uuid4().hex[:8]
    message = req.message
    conv_id = req.conv_id

    # 初始化请求计时
    timings = init_request_timings()
    logger.info("[%s] query=%s", request_id, message[:80])

    # 合同审查模式
    if req.contract_id:
        contract = db.get_contract(req.contract_id, user["id"])
        if not contract:
            return StreamingResponse(_error_stream("❌ 合同不存在或无权访问"), media_type="text/event-stream")

        logger.info("[%s] contract_review: %s", request_id, contract["filename"])
        try:
            contexts = retrieve_laws_for_contract(contract["full_text"])
            logger.info("[%s] retrieved=%d", request_id, len(contexts))
        except Exception as e:
            logger.error("[%s] retrieval failed: %s", request_id, e)
            return StreamingResponse(_error_stream(f"❌ 法律条文检索失败：{e}"), media_type="text/event-stream")

        low_confidence = contexts[0].get("_low_confidence", False) if contexts else False
        msgs = build_review_messages(req.history, contexts, contract["full_text"], message)
    else:
        try:
            contexts = multi_retrieve(message)
            logger.info("[%s] retrieved=%d", request_id, len(contexts))
            log_timings(request_id, get_timings())
        except Exception as e:
            logger.error("[%s] retrieval failed: %s", request_id, e)
            return StreamingResponse(_error_stream(f"❌ 检索失败：{e}"), media_type="text/event-stream")

        low_confidence = contexts[0].get("_low_confidence", False) if contexts else True
        msgs = build_messages(req.history, contexts, message)

    async def generate():
        full_answer = ""
        interrupted = False
        source_list = []
        for c in contexts:
            meta = c.get("meta", {})
            source_list.append({
                "text_preview": c["text"][:150],
                "source": meta.get("source", "unknown"),
                "article": meta.get("article", ""),
                "chapter": meta.get("chapter", ""),
                "score": round(c.get("rerank_score") or c.get("score", 0), 3),
            })
        yield f"data: {json.dumps({'sources': source_list}, ensure_ascii=False)}\n\n"

        try:
            for idx, chunk in enumerate(llm.generate_stream(msgs)):
                if idx % 5 == 0 and await request.is_disconnected():
                    logger.info("[%s] client disconnected after %d tokens", request_id, idx)
                    interrupted = True
                    break
                full_answer += chunk
                yield f"data: {json.dumps({'token': chunk, 'done': False}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning("[%s] LLM generation failed: %s", request_id, e)
            yield f"data: {json.dumps({'token': '', 'error': f'❌ API 调用失败：{e}', 'done': True}, ensure_ascii=False)}\n\n"
            return

        # 中断时保存已生成的部分
        msg_content = full_answer
        if interrupted:
            msg_content += "\n\n⚠️ *回答生成中断，以上为部分结果*"

        try:
            full_history = list(req.history)
            full_history.append({"role": "user", "content": message})
            full_history.append({"role": "assistant", "content": msg_content})
            db.save_conversation(conv_id, user["id"], message, full_history)
        except Exception:
            logger.warning("[%s] save conversation failed", request_id)

        done_payload = {"done": True, "sources": source_list}
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

    # 后台线程预热模型，不阻塞启动
    def _warmup():
        global _model_ready
        try:
            from models.embeddings import get_tokenizer_and_model
            get_tokenizer_and_model()
            logger.info("[OK] BGE 模型预热完成")
        except Exception as e:
            logger.warning(f"[WARN] BGE 模型预热异常：{e}")

        # Reranker 也一并预热
        try:
            from models.reranker import _lazy_load as load_reranker
            load_reranker()
            logger.info("[OK] Reranker 模型预热完成")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[WARN] Reranker 预热异常：{e}")

        _model_ready = True
        logger.info("[OK] 全部模型预热完成")

    thread = threading.Thread(target=_warmup, daemon=True)
    thread.start()
