"""API 公共工具 — 供多个中间件/路由复用的辅助函数。

避免在各个模块间重复定义相同逻辑。
"""

from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（兼容反向代理）。

    优先读取 X-Forwarded-For 头，回退到直连 IP。
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
