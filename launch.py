"""一键启动脚本 — 同时启动 FastAPI 后端 + Gradio 前端"""

import subprocess
import sys
import os
import signal
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))


def _stream_stdout(proc, prefix):
    """在独立线程中读取子进程输出，避免互相阻塞。"""
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

    gradio_proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )

    t1 = threading.Thread(target=_stream_stdout, args=(api_proc, "API"), daemon=True)
    t2 = threading.Thread(target=_stream_stdout, args=(gradio_proc, "Gradio"), daemon=True)
    t1.start()
    t2.start()

    def cleanup(signum=None, frame=None):
        print("\n正在关闭服务...")
        api_proc.terminate()
        gradio_proc.terminate()
        api_proc.wait()
        gradio_proc.wait()
        print("已关闭")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("[OK] FastAPI 后端: http://127.0.0.1:8000")
    print("[OK] Gradio 界面: http://127.0.0.1:7860")
    print()
    print("按 Ctrl+C 停止所有服务")

    try:
        signal.pause()
    except AttributeError:
        t1.join()
        t2.join()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
