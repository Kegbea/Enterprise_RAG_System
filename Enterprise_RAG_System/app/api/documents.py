"""文档上传 API — 薄路由层。

职责：参数解析 + 调用 IngestionService + 返回响应。
不含任何业务逻辑。
"""

from fastapi import APIRouter, UploadFile, File, Form, Request
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _parse_tags(tags_str: str) -> list[str]:
    """解析逗号分隔的标签字符串。"""
    if not tags_str.strip():
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]


def _parse_custom_metadata(json_str: str) -> dict[str, str]:
    """解析 JSON 格式的自定义元数据。"""
    import json
    if not json_str.strip():
        return {}
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"_raw": json_str}


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    department_id: str = Form("public"),
    tags: str = Form(""),
    custom_metadata: str = Form("{}"),
    overwrite: bool = Form(False),
):
    """上传文档并触发 ETL 入库。

    - **file**: 文档文件（PDF/DOCX/MD/TXT）
    - **department_id**: 部门标识
    - **tags**: 逗号分隔的业务标签
    - **custom_metadata**: JSON 格式的自定义元数据
    - **overwrite**: 是否覆盖已存在的相同文档
    """
    service: IngestionService = request.app.state.ingestion_service
    result = await service.ingest_upload(
        file=file,
        department_id=department_id,
        tags=_parse_tags(tags),
        custom_metadata=_parse_custom_metadata(custom_metadata),
        overwrite=overwrite,
    )
    return result


@router.get("/status/{checksum}")
async def check_status(request: Request, checksum: str):
    """通过 checksum 检查文档是否已入库。"""
    store = request.app.state.ingestion_service.pipeline.store
    existing = store.get(where={"checksum": checksum})
    return {
        "checksum": checksum,
        "exists": bool(existing and existing["ids"]),
        "chunk_count": len(existing["ids"]) if existing and existing["ids"] else 0,
    }
