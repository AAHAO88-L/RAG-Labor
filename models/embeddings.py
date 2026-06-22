from transformers import AutoTokenizer, AutoModel
import torch
import numpy as np
import os
import requests
from urllib.parse import quote

_MODEL_NAME = "BAAI/bge-large-zh-v1.5"
_tokenizer = None
_model = None

def get_tokenizer_and_model():
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        # 尝试从镜像下载到本地缓存目录（如果设置了 HF_MIRROR）
        mirror = os.getenv('HF_MIRROR', 'https://hf-mirror.com')
        repo_dir = os.path.join(os.getcwd(), 'hf_models', _MODEL_NAME.replace('/', '-'))
        if not os.path.exists(repo_dir):
            os.makedirs(repo_dir, exist_ok=True)
            _download_repo_from_mirror(_MODEL_NAME, repo_dir, mirror)
        # 优先从本地加载（local_files_only），若未完全下载则回退到网络加载
        try:
            _tokenizer = AutoTokenizer.from_pretrained(repo_dir, local_files_only=True)
            _model = AutoModel.from_pretrained(repo_dir, local_files_only=True)
        except Exception:
            # 回退：直接从远端（transformers 会使用 huggingface_hub）
            _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
            _model = AutoModel.from_pretrained(_MODEL_NAME)
        _model.eval()
    return _tokenizer, _model

def embed_texts(texts, batch_size=32, device=None):
    tokenizer, model = get_tokenizer_and_model()
    if device is None:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(device)
    embeddings = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            encoded = tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors='pt')
            for k, v in encoded.items():
                encoded[k] = v.to(device)
            out = model(**encoded)
            # 取 [CLS] 或池化：使用 mean pooling
            last_hidden = out.last_hidden_state  # (b, seq, dim)
            mask = encoded['attention_mask'].unsqueeze(-1)
            summed = (last_hidden * mask).sum(1)
            counts = mask.sum(1).clamp(min=1)
            batch_emb = (summed / counts).cpu().numpy()
            embeddings.append(batch_emb)
    return np.vstack(embeddings)


def _download_repo_from_mirror(repo, dest, mirror_base):
    """尝试从镜像下载常见的模型文件到本地目录。"""
    files = [
        'config.json',
        'tokenizer.json',
        'tokenizer_config.json',
        'vocab.txt',
        'merges.txt',
        'special_tokens_map.json',
        'pytorch_model.bin',
        'pytorch_model.bin.index.json',
        'model.safetensors'
    ]
    for fname in files:
        url = f"{mirror_base}/{quote(repo)}/resolve/main/{fname}"
        try:
            r = requests.get(url, stream=True, timeout=15)
            if r.status_code == 200:
                path = os.path.join(dest, fname)
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(32768):
                        if chunk:
                            f.write(chunk)
                print(f"Downloaded {fname} from mirror")
            else:
                # skip missing files
                pass
        except Exception as e:
            # 网络或超时等错误，继续尝试下一个文件
            print(f"镜像下载 {fname} 失败: {e}")
