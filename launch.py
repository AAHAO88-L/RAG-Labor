"""一键启动脚本 — 启动 FastAPI 后端（含静态文件服务 + SPA）"""

import subprocess
import sys
import os
import signal
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))


def _stream_stdout(proc, prefix):
    for line in iter(proc.stdout.readline, ""):
        if line:
            print(f"[{prefix}] {line}", end="", flush=True)
    proc.stdout.close()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 50)
    print("  RAG-Labor 启动中...")
    print("=" * 50)

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )

    t = threading.Thread(target=_stream_stdout, args=(api_proc, "API"), daemon=True)
    t.start()

    def cleanup(signum=None, frame=None):
        print("\n正在关闭服务...")
        api_proc.terminate()
        api_proc.wait()
        print("已关闭")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("[OK] FastAPI 后端: http://127.0.0.1:8000")
    print("[OK] 前端 SPA: http://127.0.0.1:8000")
    print()
    print("按 Ctrl+C 停止所有服务")

    try:
        signal.pause()
    except AttributeError:
        t.join()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
