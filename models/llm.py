import os
import json
import hashlib
import time
import requests
from dotenv import load_dotenv

# 强制从 .env 加载（以本文件所在目录为准）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=_env_path, override=True)

DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")

# LLM 响应缓存：messages → response text
_llm_cache: dict[str, str] = {}
_LLM_CACHE_MAX = 64

# 重试配置
_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0  # 秒


def _llm_cache_key(messages: list) -> str:
    """messages 列表的确定性 MD5 哈希作为缓存键。"""
    raw = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode()).hexdigest()


def _get_api_key():
    """每次调用时实时读取 API Key，避免缓存问题。"""
    # 先尝试直接从 .env 文件读取（绕过 os.environ 缓存）
    from dotenv import dotenv_values
    env_vals = dotenv_values(_env_path)
    if env_vals.get("DEEPSEEK_API_KEY"):
        return env_vals["DEEPSEEK_API_KEY"]
    # fallback 到环境变量
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key
    raise RuntimeError("请在 .env 文件中设置 DEEPSEEK_API_KEY")


def _api_call(payload, stream=False, timeout=120):
    """带指数退避重试的 API 调用。"""
    import logging
    logger = logging.getLogger(__name__)
    api_key = _get_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    url = f"{DEEPSEEK_API_URL.rstrip('/')}/chat/completions"

    last_exc = None
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, stream=stream, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < _RETRY_MAX:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("API 请求失败（第 %d 次），%.1fs 后重试: %s", attempt, delay, e)
                time.sleep(delay)
                continue
        except requests.HTTPError as e:
            # 4xx 错误不重试，直接抛出
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            last_exc = e
            if attempt < _RETRY_MAX:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("API HTTP 错误（第 %d 次），%.1fs 后重试: %s", attempt, delay, e)
                time.sleep(delay)
                continue
            raise
    raise last_exc or RuntimeError("API 请求失败（已达最大重试次数）")


def generate(messages, max_tokens=1024, model="deepseek-chat"):
    # 缓存命中检查
    key = _llm_cache_key(messages)
    if key in _llm_cache:
        return _llm_cache[key]

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0.3
    }
    resp = _api_call(payload, stream=False, timeout=60)
    data = resp.json()
    result = data["choices"][0]["message"]["content"]

    # 写入缓存，超过上限时淘汰最旧的
    _llm_cache[key] = result
    if len(_llm_cache) > _LLM_CACHE_MAX:
        for _ in range(16):
            _llm_cache.pop(next(iter(_llm_cache)), None)

    return result


def generate_stream(messages, max_tokens=1024, model="deepseek-chat"):
    """流式生成，逐个 yield token。"""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": 0.3
    }
    resp = _api_call(payload, stream=True, timeout=120)

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data_str = line[6:]
            if data_str.strip() == '[DONE]':
                break
            try:
                import json
                data = json.loads(data_str)
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
            except json.JSONDecodeError:
                continue


def generate_simple(prompt, max_tokens=1024):
    return generate([{"role": "user", "content": prompt}], max_tokens=max_tokens)
