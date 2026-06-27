"""检索质量评估脚本（Recall@k、MRR）。"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.eval_dataset import get_eval_dataset
from retrieval.hybrid import hybrid_retrieve
from main import chroma_retrieve, multi_retrieve


def _recall_at_k(retrieved, relevant_texts, k):
    """Recall@k：top-k 结果中包含的关联文本比例。"""
    if not relevant_texts:
        return 0.0
    retrieved_texts = [r["text"][:200] for r in retrieved[:k]]
    found = 0
    for rel in relevant_texts:
        if any(rel in rt for rt in retrieved_texts):
            found += 1
    return found / len(relevant_texts)


def _mrr(retrieved, relevant_texts):
    """MRR：第一个关联结果的倒数排名。"""
    for i, r in enumerate(retrieved):
        for rel in relevant_texts:
            if rel in r["text"][:200]:
                return 1.0 / (i + 1)
    return 0.0


def evaluate_retrieval(retrieval_fn, top_k=5, label="retrieval"):
    dataset = get_eval_dataset()
    total_recall = 0.0
    total_mrr = 0.0
    n = len(dataset)

    print(f"\n{'='*60}")
    print(f"Evaluating: {label} (top_k={top_k}, {n} queries)")
    print(f"{'='*60}")

    for i, item in enumerate(dataset):
        query = item["query"]
        relevant = item["relevant_texts"]

        results = retrieval_fn(query, top_k=top_k)

        recall = _recall_at_k(results, relevant, top_k)
        mrr = _mrr(results, relevant)

        total_recall += recall
        total_mrr += mrr

        print(f"  [{i+1:2d}] q={query[:30]:30s} recall@{top_k}={recall:.2f}  MRR={mrr:.2f}")

    avg_recall = total_recall / n
    avg_mrr = total_mrr / n

    print(f"{'─'*60}")
    print(f"  avg Recall@{top_k}: {avg_recall:.3f}")
    print(f"  avg MRR:         {avg_mrr:.3f}")
    print(f"{'='*60}\n")

    return {"recall": avg_recall, "mrr": avg_mrr}


def run_all_evaluations():
    results = {}
    results["hybrid_retrieve"] = evaluate_retrieval(
        lambda q, tk: hybrid_retrieve(q, top_k=tk), top_k=5, label="hybrid_retrieve (BM25 + 稠密)"
    )
    results["chroma_only"] = evaluate_retrieval(
        lambda q, tk: chroma_retrieve(q, top_k=tk), top_k=5, label="chroma_retrieve (仅稠密)"
    )
    return results


if __name__ == "__main__":
    run_all_evaluations()
