"""审计日志中间件 — 记录所有 HTTP 请求的审计信息。

记录字段：
- timestamp: ISO 8601 时间戳
- client_ip: 客户端 IP（兼容反向代理）
- method: HTTP 方法
- path: 请求路径
- status_code: 响应状态码
- duration_ms: 请求耗时（毫秒）
- user_agent: 客户端标识
- auth_status: 认证状态

所有日志通过 logging.getLogger("audit") 输出，可独立配置 handler。
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.api._utils import get_client_ip
from app.config import settings

audit_logger = logging.getLogger("audit")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """请求审计日志中间件。

    记录每个 HTTP 请求的审计信息到 audit logger。
    基于隐私考虑，不记录请求体和查询参数。
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        ip = get_client_ip(request)
        authed = (
            settings.api_key
            and request.headers.get("X-API-Key") == settings.api_key
        )
        auth = "authenticated" if authed else "anonymous"
        user_agent = request.headers.get("User-Agent", "-")

        audit_logger.info(
            "request",
            extra={
                "client_ip": ip,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "user_agent": user_agent,
                "auth_status": auth,
            },
        )

        return response
