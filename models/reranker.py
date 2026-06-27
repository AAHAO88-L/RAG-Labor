"""Cross-encoder 重排序器 — BGE-reranker-base，惰性加载 + 镜像下载"""

import torch
import os
import requests
from urllib.parse import quote
from transformers import AutoModelForSequenceClassification, AutoTokenizer

_RERANKER_NAME = "BAAI/bge-reranker-base"
_model = None
_tokenizer = None
_device = None


def _download_from_mirror(repo, dest, mirror_base):
    """从镜像下载 reranker 模型文件到本地。"""
    files = [
        'config.json',
        'tokenizer.json',
        'tokenizer_config.json',
        'special_tokens_map.json',
        'model.safetensors',
    ]
    for fname in files:
        url = f"{mirror_base}/{quote(repo)}/resolve/main/{fname}"
        try:
            r = requests.get(url, stream=True, timeout=30)
            if r.status_code == 200:
                path = os.path.join(dest, fname)
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(32768):
                        if chunk:
                            f.write(chunk)
                print(f"  [Reranker] 下载 {fname}")
        except Exception as e:
            print(f"  [Reranker] 镜像下载 {fname} 失败: {e}")


def _lazy_load():
    global _model, _tokenizer, _device
    if _model is not None:
        return
    _device = 'cuda' if torch.cuda.is_available() else 'cpu'

    # 镜像下载逻辑（同 embeddings.py）
    mirror = os.getenv('HF_MIRROR', 'https://hf-mirror.com')
    repo_dir = os.path.join(os.getcwd(), 'hf_models', _RERANKER_NAME.replace('/', '-'))
    if not os.path.exists(repo_dir):
        os.makedirs(repo_dir, exist_ok=True)
        _download_from_mirror(_RERANKER_NAME, repo_dir, mirror)

    try:
        _tokenizer = AutoTokenizer.from_pretrained(repo_dir, local_files_only=True)
        _model = AutoModelForSequenceClassification.from_pretrained(repo_dir, local_files_only=True)
    except Exception:
        print("  [Reranker] 本地未找到，尝试从 HuggingFace Hub 加载...")
        _tokenizer = AutoTokenizer.from_pretrained(_RERANKER_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(_RERANKER_NAME)

    _model.eval()
    _model.to(_device)
    print(f"  [Reranker] {_RERANKER_NAME} 已加载到 {_device}")


def rerank(query, candidates, top_k=5):
    """对候选文档进行 cross-encoder 重排序，返回重排序后的 top_k。

    Args:
        query: 用户原始问题
        candidates: list[dict]，每项至少含 {"text": str, ...}
        top_k: 保留的数量

    Returns:
        list[dict]: 结构与输入相同，增加 "rerank_score" 键，按分数降序
    """
    _lazy_load()

    if not candidates:
        return []

    pairs = [(query, c["text"]) for c in candidates]
    inputs = _tokenizer(
        pairs, padding=True, truncation=True, max_length=512, return_tensors="pt"
    )
    for k, v in inputs.items():
        inputs[k] = v.to(_device)

    with torch.no_grad():
        outputs = _model(**inputs)
        scores = outputs.logits.squeeze(-1).cpu().numpy().tolist()

    if isinstance(scores, (int, float)):
        scores = [scores]

    for i, c in enumerate(candidates):
        c["rerank_score"] = round(scores[i] if i < len(scores) else 0, 4)

    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

    # 阈值压缩：从第 2 条开始，如果 rerank_score < top1 * 0.5，截断
    # 最少保留 2 条，最多 top_k 条
    if len(candidates) > 2:
        top1_score = candidates[0]["rerank_score"]
        cutoff = 2  # 至少保留 2 条
        for i in range(2, len(candidates)):
            if candidates[i]["rerank_score"] < top1_score * 0.5:
                break
            cutoff = i + 1
        candidates = candidates[:max(cutoff, min(2, top_k))]

    return candidates[:top_k]
