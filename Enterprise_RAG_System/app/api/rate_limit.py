"""速率限制中间件 — 基于 IP 的滑动窗口限流。

零外部依赖，纯内存实现。根据端点类型应用不同限速策略：
- /api/chat/*     30 req/min
- /api/documents/*  10 req/min
- /api/*           60 req/min（默认兜底）
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.api._utils import get_client_ip

# ── 限速配置 ────────────────────────────────────────────

# 窗口大小（秒）
WINDOW_SECONDS = 60

# 各路径前缀的每分钟请求上限
RATE_LIMITS: dict[str, int] = {
    "/api/chat/": 30,
    "/api/documents/": 10,
}

# 默认上限（匹配未显式配置的 /api/* 路径）
DEFAULT_LIMIT = 60

# 每个 IP 最多保留的时间戳数量（防止恶意 IP 洪水撑大列表）
MAX_TIMESTAMPS_PER_IP = 200

# ── 状态 ────────────────────────────────────────────────

# {ip: [timestamp, ...]}
_hits: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()

# 定期清理定时器（惰性启动，避免 import 时创建线程）
_cleanup_timer: threading.Timer | None = None
_cleanup_started = False


def _cleanup_old_entries() -> None:
    """清理超过 2 倍窗口期未活动的 IP 记录，避免内存泄漏。"""
    now = time.monotonic()
    cutoff = now - 2 * WINDOW_SECONDS
    with _lock:
        stale = [
            ip for ip, timestamps in _hits.items()
            if (not timestamps or timestamps[-1] < cutoff)
        ]
        for ip in stale:
            del _hits[ip]


def _ensure_cleanup_timer() -> None:
    """惰性启动定期清理定时器（首次 dispatch 时调用）。"""
    global _cleanup_timer, _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    _schedule_cleanup()


def _schedule_cleanup() -> None:
    """每隔 5 分钟触发一次过期记录清理。"""
    global _cleanup_timer
    try:
        _cleanup_old_entries()
    except Exception:
        pass
    _cleanup_timer = threading.Timer(300, _schedule_cleanup)
    _cleanup_timer.daemon = True
    _cleanup_timer.start()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 IP 的滑动窗口速率限制中间件。

    仅对 /api/* 路径生效。返回 429 Too Many Requests。
    首次请求时惰性启动清理定时器，避免模块导入的副作用。
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # 惰性启动清理定时器
        _ensure_cleanup_timer()

        # 确定限速值
        limit = DEFAULT_LIMIT
        for prefix, cap in RATE_LIMITS.items():
            if path.startswith(prefix):
                limit = cap
                break

        # 滑动窗口检查
        ip = get_client_ip(request)
        now = time.monotonic()
        window_start = now - WINDOW_SECONDS

        with _lock:
            timestamps = _hits[ip]
            # 淘汰窗口外的旧记录
            while timestamps and timestamps[0] < window_start:
                timestamps.pop(0)

            # 防御：单个 IP 时间戳数超出上限时截断最旧的
            if len(timestamps) >= MAX_TIMESTAMPS_PER_IP:
                overflow = len(timestamps) - MAX_TIMESTAMPS_PER_IP + 1
                del timestamps[:overflow]

            if len(timestamps) >= limit:
                retry_after = int(timestamps[0] + WINDOW_SECONDS - now) + 1
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "请求过于频繁，请稍后再试。",
                        "error_code": "RATE_LIMITED",
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )

            timestamps.append(now)

        return await call_next(request)
