"""混合检索模块 — BM25 稀疏检索 + RRF 融合"""

import os
import json
import re
from rank_bm25 import BM25Okapi
from main import chroma_retrieve
from utils.timing import TimingScope

CHROMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_db")
_BM25_INDEX_PATH = os.path.join(CHROMA_PATH, "bm25_index.json")

_bm25 = None
_bm25_corpus = []
_bm25_metadatas = []


def _tokenize(text):
    """中文分词：character bigram + 保留原短语。"""
    text = re.sub(r'\s+', '', text)
    tokens = set()
    for i in range(len(text) - 1):
        tokens.add(text[i:i + 2])
    if len(text) <= 20:
        tokens.add(text)
    else:
        for part in re.split(r'[，。！？、；：""''（）《》\n]', text):
            part = part.strip()
            if 2 <= len(part) <= 20:
                tokens.add(part)
            elif len(part) > 20:
                for i in range(len(part) - 1):
                    tokens.add(part[i:i + 2])
    return list(tokens)


def _save_index():
    """将当前内存中的 BM25 索引持久化。"""
    data = {
        "texts": _bm25_corpus,
        "metadatas": _bm25_metadatas,
    }
    os.makedirs(os.path.dirname(_BM25_INDEX_PATH), exist_ok=True)
    with open(_BM25_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def build_bm25_index(texts, metadatas):
    """全量构建 BM25 索引并持久化。"""
    global _bm25, _bm25_corpus, _bm25_metadatas

    _bm25_corpus = list(texts)
    _bm25_metadatas = list(metadatas)
    tokenized = [_tokenize(t) for t in _bm25_corpus]
    _bm25 = BM25Okapi(tokenized)
    _save_index()
    print(f"  BM25 索引已保存 ({len(texts)} 条)")


def add_to_bm25_index(texts, metadatas):
    """增量添加文档到 BM25 索引（追加到 JSON，全量重建内存索引）。"""
    global _bm25, _bm25_corpus, _bm25_metadatas

    # 确保已加载
    _load_bm25()

    _bm25_corpus.extend(texts)
    _bm25_metadatas.extend(metadatas)
    tokenized = [_tokenize(t) for t in _bm25_corpus]
    _bm25 = BM25Okapi(tokenized)
    _save_index()


def remove_from_bm25_index(source_path):
    """按 source 路径从 BM25 索引中删除对应文档并重建索引。

    Args:
        source_path: metadata 中的 source 字段值

    Returns:
        int: 删除的片段数，0 表示未找到
    """
    global _bm25, _bm25_corpus, _bm25_metadatas

    _load_bm25()

    keep_texts = []
    keep_metadatas = []
    removed = 0
    for t, m in zip(_bm25_corpus, _bm25_metadatas):
        if m.get("source") != source_path:
            keep_texts.append(t)
            keep_metadatas.append(m)
        else:
            removed += 1

    if removed == 0:
        return 0

    _bm25_corpus = keep_texts
    _bm25_metadatas = keep_metadatas
    tokenized = [_tokenize(t) for t in _bm25_corpus]
    _bm25 = BM25Okapi(tokenized)
    _save_index()
    return removed


def _load_bm25():
    """惰性加载 BM25 索引。"""
    global _bm25, _bm25_corpus, _bm25_metadatas
    if _bm25 is not None:
        return _bm25, _bm25_corpus

    if not os.path.exists(_BM25_INDEX_PATH):
        raise FileNotFoundError("BM25 索引不存在，请先运行 ingest.py")

    with open(_BM25_INDEX_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    _bm25_corpus = data["texts"]
    _bm25_metadatas = data.get("metadatas", [{}] * len(_bm25_corpus))
    tokenized = [_tokenize(t) for t in _bm25_corpus]
    _bm25 = BM25Okapi(tokenized)
    return _bm25, _bm25_corpus


def bm25_retrieve(query, top_k=10):
    """纯 BM25 检索。"""
    with TimingScope("bm25_retrieve"):
        bm25, corpus = _load_bm25()
        q_tokens = _tokenize(query)
        scores = bm25.get_scores(q_tokens)

        indexed = [(scores[i], i) for i in range(len(scores))]
        indexed.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, idx in indexed[:top_k]:
            if score <= 0:
                continue
            meta = _bm25_metadatas[idx] if idx < len(_bm25_metadatas) else {}
            results.append({
                "text": corpus[idx],
                "meta": meta,
                "bm25_score": round(float(score), 4),
                "bm25_index": idx,
            })
        return results


def _rrf_fuse(dense_results, sparse_results, k=60):
    """Reciprocal Rank Fusion."""
    rank_map = {}

    for rank_i, r in enumerate(dense_results):
        key = r["text"]
        if key not in rank_map:
            rank_map[key] = {"text": key, "meta": r.get("meta", {}), "dense_score": r.get("score", 0), "bm25_score": 0}
        rank_map[key]["rrf"] = rank_map[key].get("rrf", 0) + 1.0 / (k + rank_i + 1)
        rank_map[key]["dense_score"] = r.get("score", 0)

    for rank_i, r in enumerate(sparse_results):
        key = r["text"]
        if key not in rank_map:
            rank_map[key] = {"text": key, "meta": r.get("meta", {}), "dense_score": 0, "bm25_score": r.get("bm25_score", 0)}
        rank_map[key]["rrf"] = rank_map[key].get("rrf", 0) + 1.0 / (k + rank_i + 1)
        rank_map[key]["bm25_score"] = r.get("bm25_score", 0)

    return sorted(rank_map.values(), key=lambda x: x["rrf"], reverse=True)


def hybrid_retrieve(query, top_k=10, rrf_k=60):
    """混合检索：BM25 + ChromaDB，RRF 融合排序。"""
    with TimingScope("hybrid_retrieve"):
        dense_results = chroma_retrieve(query, top_k=top_k * 2)
        sparse_results = bm25_retrieve(query, top_k=top_k * 2)

        fused = _rrf_fuse(dense_results, sparse_results, k=rrf_k)

        results = []
        for i, item in enumerate(fused[:top_k]):
            rrf_score = item.get("rrf", 0)
            max_rrf = fused[0].get("rrf", 1) if fused else 1
            norm_score = round(rrf_score / max_rrf if max_rrf > 0 else 0, 4)
            results.append({
                "text": item["text"],
                "meta": item["meta"],
                "score": norm_score,
                "rrf_score": round(rrf_score, 4),
                "dense_score": item.get("dense_score", 0),
                "bm25_score": item.get("bm25_score", 0),
                "distance": 0,
            })
        return results
