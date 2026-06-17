"""API Key 认证中间件。

当 settings.api_key 非空时，所有 /api/* 请求必须携带 X-API-Key header。
当 settings.api_key 为空时（默认），认证检查跳过（开发兼容）。
"""

from __future__ import annotations

import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings


class APIKeyMiddleware(BaseHTTPMiddleware):
    """API Key 认证中间件 — 检查 X-API-Key header。

    仅对 /api/* 路径生效，跳过 /health 和 /docs 等公开端点。
    使用 secrets.compare_digest 做恒定时间比较，防止时序攻击。
    """

    async def dispatch(self, request: Request, call_next):
        # 仅对 API 路由生效，放行健康检查、文档等公开端点
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        if not settings.api_key:
            return await call_next(request)

        client_key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(client_key, settings.api_key):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "缺少或无效的 API Key。请在 X-API-Key header 中提供有效的密钥。",
                    "error_code": "UNAUTHORIZED",
                },
            )

        return await call_next(request)
