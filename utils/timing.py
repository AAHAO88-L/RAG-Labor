"""结构化耗时追踪 — 每个请求各阶段耗时记录"""

import time
import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_request_timings: ContextVar[dict] = ContextVar("request_timings", default=None)


class TimingScope:
    """上下文管理器，记录命名阶段的耗时。"""

    def __init__(self, stage_name: str):
        self.stage = stage_name
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self.start
        timings = _request_timings.get()
        if timings is not None and self.stage not in timings:
            timings[self.stage] = round(elapsed, 4)


def init_request_timings() -> dict:
    """在请求开始时调用，初始化计时上下文。返回 timings dict。"""
    d: dict = {}
    _request_timings.set(d)
    return d


def get_timings() -> dict:
    """获取当前请求的耗时数据。"""
    return _request_timings.get() or {}


def log_timings(request_id: str, timings: dict = None):
    """输出一条结构化耗时日志。"""
    if timings is None:
        timings = get_timings()
    if not timings:
        return
    parts = " | ".join(f"{k}={v}s" for k, v in sorted(timings.items()))
    logger.info("[%s] TIMING %s", request_id, parts)
