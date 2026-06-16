"""聊天 API — 薄路由层。

暴露 POST /api/chat/stream SSE 流式对话端点。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.query_service import QueryService

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """聊天请求体。"""
    query: str = Field(..., description="用户问题", min_length=1)
    chat_history: list[dict[str, str]] | None = Field(
        default=None,
        description="对话历史 [{\"role\":\"user\",\"content\":\"...\"}, ...]",
    )


@router.post("/stream")
async def chat_stream(request: Request, body: ChatRequest):
    """SSE 流式对话端点。

    返回 text/event-stream，事件类型：
    - citation: 检索到的引用来源
    - token: LLM 生成的文本增量
    - done: 结束信号

    引擎未就绪时返回 503（有文体但无文档）。
    """
    service: QueryService = request.app.state.query_service

    # 预检：引擎未就绪时返回明确的 HTTP 错误（而非在流中抛异常）
    if not service.ensure_ready():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "RAG 引擎未就绪：请先上传文档。POST /api/documents/upload",
                "error_code": "ENGINE_NOT_READY",
            },
        )

    async def event_generator():
        async for sse_event in service.query_stream(
            query=body.query,
            chat_history=body.chat_history,
        ):
            yield sse_event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
