import os
import requests
from dotenv import load_dotenv

# 强制从 .env 加载（以本文件所在目录为准）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(dotenv_path=_env_path, override=True)

DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com")


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


def generate(messages, max_tokens=1024, model="deepseek-chat"):
    api_key = _get_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0.3
    }
    url = f"{DEEPSEEK_API_URL.rstrip('/')}/chat/completions"
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def generate_stream(messages, max_tokens=1024, model="deepseek-chat"):
    """流式生成，逐个 yiled token。"""
    api_key = _get_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": 0.3
    }
    url = f"{DEEPSEEK_API_URL.rstrip('/')}/chat/completions"
    resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()

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
