import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def lifespan():
    """确保 lifespan startup 被执行。"""
    async with app.router.lifespan_context(app):
        yield


@pytest.mark.anyio
async def test_upload_document_txt():
    """测试上传 TXT 文件。"""
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents/status/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data


@pytest.mark.anyio
async def test_health_check():
    """确认 /health 端点仍正常。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
