"""聊天 API 端点测试。

测试策略：
- 结构测试：验证请求模型、路由注册、响应格式（不依赖 API key）
- 错误场景：无文档时返回 503、无效 JSON 返回 422
- 集成测试：需要有效 DASHSCOPE_API_KEY，用 RUN_RAG_TESTS=1 手动运行
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def lifespan(monkeypatch, tmp_path):
    """确保 lifespan startup 使用隔离的临时存储。"""
    storage = tmp_path / "test_storage"
    monkeypatch.setenv("storage_dir", str(storage))
    from app.config import Settings

    monkeypatch.setattr("app.config.settings", Settings())
    monkeypatch.setattr("app.main.settings", Settings())

    from app.main import app
    async with app.router.lifespan_context(app):
        yield


# ── 请求模型测试 ────────────────────────────────────────


class TestChatRequestModel:
    def test_valid_request(self):
        from app.api.chat import ChatRequest

        req = ChatRequest(query="什么是RAG？")
        assert req.query == "什么是RAG？"
        assert req.chat_history is None

    def test_with_history(self):
        from app.api.chat import ChatRequest

        history = [{"role": "user", "content": "你好"}]
        req = ChatRequest(query="继续", chat_history=history)
        assert len(req.chat_history) == 1

    def test_empty_query_rejected(self):
        from pydantic import ValidationError

        from app.api.chat import ChatRequest

        try:
            ChatRequest(query="")
            assert False, "应抛出 ValidationError"
        except ValidationError:
            pass


# ── 错误场景测试 ────────────────────────────────────────


@pytest.mark.anyio
async def test_chat_stream_empty_store():
    """无文档时返回 503，响应体为 JSON 错误信息。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat/stream",
            json={"query": "测试问题"},
            timeout=30,
        )

    assert response.status_code == 503
    data = response.json()
    assert "ENGINE_NOT_READY" in data.get("error_code", "")
    assert "请先上传文档" in data.get("detail", "")


@pytest.mark.anyio
async def test_chat_stream_invalid_json():
    """无效 JSON 应返回 422。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat/stream",
            content=b"not json",
            headers={"Content-Type": "application/json"},
            timeout=30,
        )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_chat_stream_after_upload_invalid_key():
    """上传文档后，若 API key 无效，引擎初始化失败 → 返回 503。

    此测试不依赖有效 API key。有有效 key 时参见 test_chat_stream_full_flow。
    """
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 先上传文档
        content = "企业知识管理系统测试文档。" * 50
        files = {"file": ("test.txt", content, "text/plain")}
        upload_resp = await client.post(
            "/api/documents/upload",
            files=files,
            data={"department_id": "engineering"},
        )
        assert upload_resp.status_code == 200
        upload_result = upload_resp.json()
        assert upload_result["status"] == "created"

        # 2. 无有效 API key 时引擎初始化失败，应返回 503
        response = await client.post(
            "/api/chat/stream",
            json={"query": "什么是企业知识管理？"},
            timeout=30,
        )

        # 初始化的 embedding 步骤可能成功（取决于 env），但 LLM 初始化失败
        # 导致引擎未就绪 → 503
        assert response.status_code == 503
        data = response.json()
        assert "ENGINE_NOT_READY" in data.get("error_code", "")


# ── 集成测试（需要有效 API key） ───────────────────────


@pytest.mark.skip(reason="需要有效的 DASHSCOPE_API_KEY，设置 RUN_RAG_TESTS=1 手动运行")
@pytest.mark.anyio
async def test_chat_stream_full_flow():
    """完整流程：上传文档 → 流式对话。

    前置条件：
        - DASHSCOPE_API_KEY 有效
        - DASHSCOPE_API_KEY 在 .env 中配置
        - 运行: RUN_RAG_TESTS=1 uv run pytest tests/test_api_chat.py -k full_flow -v
    """
    if not os.getenv("RUN_RAG_TESTS"):
        pytest.skip("Set RUN_RAG_TESTS=1 to run integration tests")

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 上传文档
        files = {
            "file": (
                "knowledge.txt",
                "企业知识管理系统（Enterprise Knowledge Management System）"
                "是一种用于捕获、存储、组织和检索企业知识的软件系统。"
                "它利用自然语言处理和机器学习技术，帮助企业高效管理非结构化文档数据。"
                .encode(),
                "text/plain",
            )
        }
        upload_resp = await client.post(
            "/api/documents/upload",
            files=files,
            data={"department_id": "engineering", "tags": "技术,AI"},
        )
        assert upload_resp.status_code == 200
        upload_result = upload_resp.json()
        assert upload_result["status"] == "created"

        # 2. 流式对话
        response = await client.post(
            "/api/chat/stream",
            json={"query": "什么是企业知识管理系统？"},
            timeout=120,
        )

        assert response.status_code == 200
        ct = response.headers.get("content-type", "")
        assert "text/event-stream" in ct

        # 3. 解析 SSE 事件
        body = response.text
        events = [line for line in body.split("\n") if line.startswith("event: ")]
        event_types = {line.split(": ")[1].strip() for line in events}
        assert "citation" in event_types, "应包含 citation 事件"
        assert "done" in event_types, "应包含 done 事件"
