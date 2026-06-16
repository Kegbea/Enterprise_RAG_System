"""API 文档上传端点测试。"""


import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def lifespan(monkeypatch, tmp_path):
    """确保 lifespan startup 使用隔离的临时存储。

    monkeypatch.setenv 必须在 Settings() 构造前调用（pydantic-settings
    在构造时读取 env），但其他测试文件（如 test_rag.py）的模块级 import
    可能已触发 Settings 单例创建。因此先 setenv，再替换已创建的单例引用。
    """
    storage = tmp_path / "test_storage"
    monkeypatch.setenv("storage_dir", str(storage))
    from app.config import Settings

    monkeypatch.setattr("app.config.settings", Settings())
    monkeypatch.setattr("app.main.settings", Settings())

    from app.main import app
    async with app.router.lifespan_context(app):
        yield


@pytest.mark.anyio
async def test_upload_document_txt():
    """测试上传 TXT 文件。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("test.txt", "企业知识管理系统测试内容。" * 30, "text/plain")}
        data = {"department_id": "engineering", "tags": "测试,dev", "overwrite": "false"}
        response = await client.post("/api/documents/upload", files=files, data=data)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] in ("created", "skipped", "error")
    assert result["status"] == "created"


@pytest.mark.anyio
async def test_upload_unsupported_type():
    """上传不支持的类型应返回错误。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("data.xyz", b"binary content", "application/octet-stream")}
        response = await client.post("/api/documents/upload", files=files)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "error"


@pytest.mark.anyio
async def test_check_status():
    """测试通过 checksum 查询文档状态。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents/status/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data


@pytest.mark.anyio
async def test_health_check():
    """确认 /health 端点仍正常。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
