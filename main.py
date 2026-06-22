import os
import json
import argparse
import chromadb
import numpy as np
from models.embeddings import embed_texts
from models import llm

DEFAULT_TOP_K = 10
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")

_collection = None


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


def retrieve_with_scores(query, top_k=DEFAULT_TOP_K):
    """ChromaDB 检索并返回带相似度分数的结果。"""
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


def retrieve(query, top_k=4):
    """保持向后兼容的简单检索接口。"""
    return [r['text'] for r in retrieve_with_scores(query, top_k=top_k)]


def rewrite_query(question):
    """Layer 3: 多路查询重写（Query Rewrite + HyDE）。
    将用户问题拆成多个角度提问，提高检索命中率。"""
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
    """HyDE（假设文档嵌入）检索：先让LLM生成一个假想回答，再用它去搜。"""
    hyde_prompt = (
        "你是一名劳动法律师。请根据以下问题，撰写一段专业、详细的回答。"
        "如果不知道具体法条，可以根据法律常识合理推断。\n\n"
        f"问题：{question}"
    )
    try:
        hypothetical_answer = llm.generate_simple(hyde_prompt, max_tokens=512)
        return retrieve_with_scores(hypothetical_answer, top_k=top_k)
    except Exception:
        return retrieve_with_scores(question, top_k=top_k)


def multi_retrieve(question, top_k=DEFAULT_TOP_K):
    """Layer 3: 多路检索 + 合并去重。
    先做 Query Rewrite 多路检索，如果结果不足再做 HyDE 兜底。"""
    queries = rewrite_query(question)
    seen_texts = set()
    merged = []

    for q in queries:
        results = retrieve_with_scores(q, top_k=top_k)
        for r in results:
            if r['text'] not in seen_texts:
                seen_texts.add(r['text'])
                merged.append(r)

    merged.sort(key=lambda x: x['score'], reverse=True)

    if len(merged) < 3:
        hyde_results = hyde_retrieve(question, top_k=top_k)
        for r in hyde_results:
            if r['text'] not in seen_texts:
                seen_texts.add(r['text'])
                merged.append(r)
        merged.sort(key=lambda x: x['score'], reverse=True)

    return merged[:top_k]


def build_messages(history, contexts, question):
    """Layer 1: 松绑系统提示词。
    - 优先根据知识库回答
    - 信息不足时允许使用自身常识
    - 必须明确标注信息来源"""
    ctx_parts = []
    for c in contexts:
        source = c.get('meta', {}).get('source', '未知来源')
        score = c.get('score', None)
        score_str = f" [匹配度:{score}]" if score else ""
        ctx_parts.append(f"来源：{source}{score_str}\n内容：{c['text']}")

    ctx_text = "\n\n---\n\n".join(ctx_parts) if ctx_parts else "（知识库未检索到相关信息）"

    system = (
        "你是劳动法智能助手。请遵循以下规则回答问题：\n\n"
        "1. 优先使用以下参考内容回答。\n"
        "2. 如果参考内容足以回答问题，直接回答。\n"
        "3. 如果参考内容信息不足，允许结合自身法律常识补充回答。\n"
        "4. 如果问题与劳动法无关或完全超出能力范围，请如实告知。\n\n"
        f"参考内容：\n{ctx_text}"
    )

    messages = [{"role": "system", "content": system}]
    for user_q, assistant_a in history:
        messages.append({"role": "user", "content": user_q})
        messages.append({"role": "assistant", "content": assistant_a})
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

    # Layer 4: 判断是否需要兜底 — 用原始L2距离判断
    # bge-large-zh-v1.5 1024维下，相关匹配距离通常 <380
    min_dist = min((c.get('distance', 9999) for c in contexts), default=9999)
    low_confidence = min_dist > 400 or len(contexts) == 0

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
        q = ' '.join(args.ask)
        history = []
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
            try:
                q = input("\n输入下一个问题（输入 q 退出）: ")
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ('q', 'quit', 'exit'):
                break
    else:
        parser.print_help()
