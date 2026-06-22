"""一键启动脚本 — 同时启动 FastAPI 后端 + Gradio 前端"""

import subprocess
import sys
import os
import signal
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    print("=" * 50)
    print("  RAG-Labor 启动中...")
    print("=" * 50)

    # 启动 FastAPI
    api_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 启动 Gradio
    gradio_proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

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

    print("✅ FastAPI 后端: http://127.0.0.1:8000")
    print("✅ Gradio 界面: http://127.0.0.1:7860")
    print()
    print("按 Ctrl+C 停止所有服务")

    # 等待子进程
    try:
        while True:
            line = api_proc.stdout.readline()
            if line:
                print(f"[API] {line}", end="")
            line2 = gradio_proc.stdout.readline()
            if line2:
                print(f"[Gradio] {line2}", end="")
            if api_proc.poll() is not None and gradio_proc.poll() is not None:
                break
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
