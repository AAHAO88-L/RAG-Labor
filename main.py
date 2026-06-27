import os
import json
import math
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4
import chromadb
import numpy as np
import re
from models.embeddings import embed_texts
from models import llm
from utils.timing import TimingScope

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")

_collection = None

# ── 查询预处理 ──

def preprocess_query(question: str) -> str:
    """基本的查询预处理。"""
    q = question.strip()
    q = re.sub(r'\s+', '', q)
    q = re.sub(r'^(请问|我想问|你好|你好请问|麻烦问一下|帮我问一下)[，,。.]*', '', q)
    if not q.endswith(('？', '?', '？')):
        q += '？'
    return q if q else question


def load_index():
    global _collection
    if _collection is not None:
        return _collection
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        _collection = client.get_collection("labor_laws")
    except Exception:
        raise FileNotFoundError("ChromaDB 集合不存在，请先运行 ingest.py 构建索引。")
    return _collection


def chroma_retrieve(query, top_k=DEFAULT_TOP_K):
    """仅 ChromaDB 稠密检索（供 retrieval/hybrid.py 直接调用）。"""
    with TimingScope("chroma_retrieve"):
        collection = load_index()
        q_emb = embed_texts([query])[0].tolist()
        results = collection.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        if not results["ids"][0]:
            return out
        distances = results["distances"][0]
        min_dist = min(distances) if distances else 0
        max_dist = max(distances) if distances else 1
        denom = max_dist - min_dist if max_dist > min_dist else 1.0
        for i, doc_id in enumerate(results["ids"][0]):
            dist = distances[i]
            score = round(1.0 - (dist - min_dist) / denom, 4)
            meta = results["metadatas"][0][i] if results["metadatas"][0] else {}
            out.append({
                "text": results["documents"][0][i],
                "meta": meta,
                "distance": float(dist),
                "score": score,
            })
        return out


def retrieve_with_scores(query, top_k=DEFAULT_TOP_K):
    """ChromaDB 检索并返回带相似度分数的结果。"""
    return chroma_retrieve(query, top_k=top_k)


def retrieve(query, top_k=4):
    """保持向后兼容的简单检索接口。"""
    return [r['text'] for r in retrieve_with_scores(query, top_k=top_k)]


def rewrite_query(question):
    """Layer 3: 多路查询重写（Query Rewrite + HyDE）。
    将用户问题拆成多个角度提问，提高检索命中率。"""
    with TimingScope("rewrite_llm"):
        rewrite_prompt = (
            "你是法律检索助手。请将用户问题从以下3个不同角度各改写1个检索式，"
            "每行一个，不要序号，不要多余文字。\n"
            "角度1：保留原意的精简关键词版\n"
            "角度2：从法律法规条文表述角度\n"
            "角度3：从劳动者权益主张角度\n\n"
            f"用户问题：{question}"
        )
        try:
            rewritten = llm.generate_simple(rewrite_prompt, max_tokens=256)
            queries = [q.strip() for q in rewritten.strip().split('\n') if q.strip()]
            # 始终保留原问题
            all_queries = [question] + queries[:3]
            return all_queries
        except Exception:
            return [question]


def hyde_retrieve(question, top_k=DEFAULT_TOP_K):
    """HyDE（假设文档嵌入）检索：先让LLM生成一个假想回答，再用混合检索去搜。"""
    from retrieval.hybrid import hybrid_retrieve
    with TimingScope("hyde_llm"):
        hyde_prompt = (
            "你是劳动法专家。请用一两句话简要回答以下问题：\n\n"
            f"问题：{question}\n\n"
            "回答："
        )
        try:
            hypothetical_answer = llm.generate_simple(hyde_prompt, max_tokens=120)
            return hybrid_retrieve(hypothetical_answer, top_k=top_k)
        except Exception:
            return hybrid_retrieve(question, top_k=top_k)


def multi_retrieve(question, top_k=DEFAULT_TOP_K):
    """并行执行 Query Rewrite + HyDE 检索，全部使用混合检索（BM25+稠密），
    合并去重后经 Reranker 精排，返回 (contexts, low_confidence)。"""
    from retrieval.hybrid import hybrid_retrieve
    question = preprocess_query(question)
    with TimingScope("multi_retrieve_total"):

        # 先做一次直接混合检索，用户可能已经在等了
        direct_results = hybrid_retrieve(question, top_k=top_k)
        seen_texts = set(r['text'] for r in direct_results)
        merged = list(direct_results)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_rewrite = pool.submit(_rewrite_then_search, question, top_k)
            f_hyde = pool.submit(_hyde_then_search, question, top_k)

            for future in as_completed([f_rewrite, f_hyde]):
                results = future.result()
                for r in (results or []):
                    if r['text'] not in seen_texts:
                        seen_texts.add(r['text'])
                        merged.append(r)

        merged.sort(key=lambda x: x['score'], reverse=True)
        if not merged:
            return []

        # Reranker 二次排序（仅在 top_k >= 3 时启用，默认开启）
        USE_RERANKER = os.getenv("USE_RERANKER", "1") == "1"
        low_confidence = True
        if USE_RERANKER and len(merged) >= 3:
            try:
                from models.reranker import rerank
                with TimingScope("reranker"):
                    merged = rerank(question, merged, top_k=min(top_k, 5))
                top_score = merged[0].get("rerank_score", 0) if merged else 0
                prob = 1.0 / (1.0 + math.exp(-top_score))
                low_confidence = prob < 0.5 if merged else True
            except Exception as e:
                logger.warning(f"Reranker 重排失败，回退原排序：{e}")
                merged = merged[:top_k]
                low_confidence = True
        else:
            merged = merged[:top_k]
            low_confidence = (merged[0].get("score", 0) < 0.3) if merged else True

        # 在上下文中嵌入低置信度标记
        for c in merged:
            c["_low_confidence"] = low_confidence

        return merged


def _rewrite_then_search(question, top_k):
    """查询改写 + 多路检索（使用混合检索）"""
    from retrieval.hybrid import hybrid_retrieve
    queries = rewrite_query(question)
    seen = set()
    merged = []
    for q in queries:
        results = hybrid_retrieve(q, top_k=top_k)
        for r in results:
            if r['text'] not in seen:
                seen.add(r['text'])
                merged.append(r)
    return merged


def _hyde_then_search(question, top_k):
    """HyDE 检索（使用混合检索）"""
    return hyde_retrieve(question, top_k=top_k)


def retrieve_laws_for_contract(contract_text, top_k=DEFAULT_TOP_K):
    """用合同文本检索相关法律条文，用于合同审查。"""
    from retrieval.hybrid import hybrid_retrieve

    # 截取合同前 2000 字作为检索查询
    query = contract_text[:2000]
    results = hybrid_retrieve(query, top_k=top_k)
    return results


def build_messages(history, contexts, question):
    """构造 RAG 问答用的 messages：系统指令 + 上下文 + 历史对话 + 当前问题。"""
    ctx_parts = []
    for c in contexts:
        meta = c.get('meta', {})
        source = meta.get('source', '未知来源')
        meta_parts = [f"来源：{source}"]
        if meta.get('article'):
            meta_parts.append(f"引用法条：{meta['article']}")
        if meta.get('chapter'):
            meta_parts.append(f"所属章节：{meta['chapter']}")
        score = c.get('rerank_score') or c.get('score', None)
        if score:
            meta_parts.append(f"匹配度：{score:.3f}")
        ctx_parts.append(f"{' | '.join(meta_parts)}\n内容：{c['text']}")

    ctx_text = "\n\n---\n\n".join(ctx_parts) if ctx_parts else "（未检索到相关法律条文）"

    system = (
        "你是一位劳动法专家助手。请根据以下提供的法律条文信息，准确回答用户的问题。"
        "回答时注意：\n"
        "1. 优先引用检索到的法律条文作为依据\n"
        "2. 如果检索到的信息不足以回答问题，请如实说明，不要编造法条\n"
        "3. 回答应简洁专业，适当引用具体法条（如《劳动合同法》第XX条）\n\n"
        f"【相关法律条文】\n{ctx_text}"
    )

    messages = [{"role": "system", "content": system}]
    for item in history:
        if isinstance(item, dict):
            messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
    messages.append({"role": "user", "content": question})
    return messages


def build_review_messages(history, contexts, contract_text, question):
    """构造合同审查专用的系统提示词。"""
    ctx_parts = []
    for c in contexts:
        meta = c.get('meta', {})
        source = meta.get('source', '未知来源')
        meta_parts = [f"来源：{source}"]
        if meta.get('article'):
            meta_parts.append(f"引用法条：{meta['article']}")
        if meta.get('chapter'):
            meta_parts.append(f"所属章节：{meta['chapter']}")
        score = c.get('rerank_score') or c.get('score', None)
        if score:
            meta_parts.append(f"匹配度：{score:.3f}")
        ctx_parts.append(f"{' | '.join(meta_parts)}\n内容：{c['text']}")

    ctx_text = "\n\n---\n\n".join(ctx_parts) if ctx_parts else "（未检索到相关法律条文）"

    system = (
        "你是一位劳动法合同审核专家。请根据《中华人民共和国劳动法》《中华人民共和国劳动合同法》"
        "及相关法律法规，对以下合同进行专业审查。\n\n"
        "请重点关注以下几方面：\n"
        "1. **违反强制性规定**：指出合同中违反劳动法律强制性规定的条款，并引用具体法律条文（如《劳动合同法》第XX条）\n"
        "2. **不公平条款**：分析可能存在对劳动者不公平、权利义务不对等的条款\n"
        "3. **缺失条款**：指出合同缺少的法定必备条款\n"
        "4. **模糊条款**：表述不清晰、可能存在歧义或争议的条款\n"
        "5. **修改建议**：对每个问题条款给出具体的修改建议\n\n"
        "格式要求：\n"
        "- 对每一条问题，标注所涉及的合同条款位置\n"
        "- 引用具体法律条文作为依据\n"
        "- 给出明确的合规判定（合规/不合规/建议修改）\n"
        "- 如有合规条款，也简要注明\n\n"
        f"【待审查合同全文】\n{contract_text}\n\n"
        f"【相关法律依据】\n{ctx_text}\n\n"
        f"用户问题：{question}"
    )

    messages = [{"role": "system", "content": system}]
    for item in history:
        if isinstance(item, dict):
            messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
    messages.append({"role": "user", "content": question})
    return messages


def ask(question, history=None, use_multi_query=True):
    """高级问答接口。"""
    if history is None:
        history = []

    # Layer 2 + 3: 多路检索
    if use_multi_query:
        contexts = multi_retrieve(question)
    else:
        contexts = retrieve_with_scores(question, top_k=4)

    # Layer 4: 判断是否需要兜底 — 优先用 rerank_score，fallback 到 L2 距离
    low_confidence = contexts[0].get("_low_confidence", False) if contexts else True

    messages = build_messages(history, contexts, question)
    answer = llm.generate(messages)

    return answer, contexts, low_confidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ingest', action='store_true', help='构建索引')
    parser.add_argument('--ask', nargs='+', help='提问')
    args = parser.parse_args()
    if args.ingest:
        import ingest
        ingest.build_index()
    elif args.ask:
        import database as db
        db.init_db()
        q = ' '.join(args.ask)
        history = []
        conv_id = uuid4().hex[:12]
        while True:
            answer, contexts, low_conf = ask(q, history)
            print("=== 回答 ===")
            print(answer)
            if low_conf:
                print("\n⚠️ 匹配度较低，部分内容可能来自模型自身知识。")
            print("=== 参考片段 ===")
            for c in contexts:
                print(f"- {c['meta']['source']} (chunk {c['meta']['chunk_id']}, score={c['score']})")
            history.append((q, answer))
            msgs = []
            for h in history:
                msgs.append({"role": "user", "content": h[0]})
                msgs.append({"role": "assistant", "content": h[1]})
            # CLI 模式存到匿名用户（user_id=0），方便后续查看
            db.save_conversation(conv_id, 0, q, msgs)
            try:
                q = input("\n输入下一个问题（输入 q 退出）: ")
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ('q', 'quit', 'exit'):
                break
    else:
        parser.print_help()
