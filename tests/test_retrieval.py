"""检索集成测试（需索引就绪，标记为 slow）。"""

import pytest

pytestmark = pytest.mark.slow


def test_chroma_retrieve_returns_list():
    """如果 ChromaDB 集合不存在，应抛 FileNotFoundError。"""
    from main import load_index
    try:
        load_index()
    except FileNotFoundError:
        pytest.skip("ChromaDB 索引不存在，跳过检索测试")


def test_hybrid_retrieve_returns_results():
    from retrieval.hybrid import hybrid_retrieve
    try:
        results = hybrid_retrieve("经济补偿金", top_k=5)
    except FileNotFoundError:
        pytest.skip("BM25 索引不存在")
    assert len(results) > 0
    assert all("text" in r for r in results)
    assert all("score" in r for r in results)


def test_hybrid_retrieve_score_order():
    from retrieval.hybrid import hybrid_retrieve
    try:
        results = hybrid_retrieve("解除劳动合同", top_k=10)
    except FileNotFoundError:
        pytest.skip("索引不存在")
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_retrieve_deduplication():
    from retrieval.hybrid import hybrid_retrieve
    try:
        results = hybrid_retrieve("试用期工资", top_k=20)
    except FileNotFoundError:
        pytest.skip("索引不存在")
    texts = [r["text"] for r in results]
    assert len(texts) == len(set(texts)), "检索结果存在重复"


def test_bm25_retrieve():
    from retrieval.hybrid import bm25_retrieve
    try:
        results = bm25_retrieve("经济补偿金", top_k=5)
    except FileNotFoundError:
        pytest.skip("BM25 索引不存在")
    assert len(results) > 0
    scores = [r["bm25_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
