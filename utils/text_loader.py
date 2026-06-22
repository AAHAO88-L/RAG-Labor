import os

def load_text_files(folder):
    """读取 folder 下的 .txt/.md 文件，返回 {path: text} 的字典"""
    results = {}
    if not os.path.exists(folder):
        return results
    for root, _, files in os.walk(folder):
        for name in files:
            if name.lower().endswith(('.txt', '.md')):
                path = os.path.join(root, name)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        results[path] = f.read()
                except Exception:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        results[path] = f.read()
    return results
