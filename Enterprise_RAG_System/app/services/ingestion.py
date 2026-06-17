"""文档入库服务 — API 和 CLI 的共享业务入口。

职责：
- 管理 ETLPipeline 实例
- 上传文件归档到 data/documents/
- 调用 pipeline.ingest_bytes()
- 返回结构化结果
- 入库成功后通知 QueryService 刷新检索索引
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings
from app.etl.pipeline import BatchIngestResult, ETLPipeline, IngestResult
from app.models.document import DocumentMetadata

if TYPE_CHECKING:
    from fastapi import UploadFile

logger = logging.getLogger(__name__)


class IngestionService:
    """文档入库服务 — API 和 CLI 的共享业务入口。"""

    def __init__(self, pipeline: ETLPipeline, archive_dir: Path | None = None):
        self.pipeline = pipeline
        self.archive_dir = Path(archive_dir) if archive_dir else Path(settings.document_archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._on_ingested: Callable[[], None] | None = None

    def set_on_ingested(self, callback: Callable[[], None]) -> None:
        """注册入库成功回调（供 QueryService.refresh 对接）。"""
        self._on_ingested = callback

    async def ingest_upload(
        self,
        file: "UploadFile",
        department_id: str = "public",
        tags: list[str] | None = None,
        custom_metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> IngestResult:
        """API 异步上传入口 — 从 UploadFile 读取并处理。"""
        content = await file.read()
        return self._process_upload(
            content=content,
            filename=file.filename or "unknown",
            department_id=department_id,
            tags=tags or [],
            custom_metadata=custom_metadata or {},
            source="api",
            overwrite=overwrite,
        )

    async def ingest_bytes(
        self,
        content: bytes,
        filename: str,
        department_id: str = "public",
        tags: list[str] | None = None,
        custom_metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> IngestResult:
        """直接传入 bytes 的异步入库入口。

        用于路由层已读取文件内容的场景，避免二次读取。
        """
        return self._process_upload(
            content=content,
            filename=filename,
            department_id=department_id,
            tags=tags or [],
            custom_metadata=custom_metadata or {},
            source="api",
            overwrite=overwrite,
        )

    def ingest_upload_sync(
        self,
        file,
        department_id: str = "public",
        tags: list[str] | None = None,
        custom_metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> IngestResult:
        """同步上传入口（供测试和 CLI 使用）。"""
        content = file.file.read()
        return self._process_upload(
            content=content,
            filename=file.filename or "unknown",
            department_id=department_id,
            tags=tags or [],
            custom_metadata=custom_metadata or {},
            source="api",
            overwrite=overwrite,
        )

    def _process_upload(
        self,
        content: bytes,
        filename: str,
        department_id: str,
        tags: list[str],
        custom_metadata: dict[str, str],
        source: str,
        overwrite: bool,
    ) -> IngestResult:
        # 归档文件
        archive_path = self.archive_dir / filename
        archive_path.write_bytes(content)

        # 构建元数据
        overrides = DocumentMetadata(
            filename=filename,
            department_id=department_id,
            tags=tags,
            custom_metadata=custom_metadata,
            source=source,
            file_size=len(content),
        )

        result = self.pipeline.ingest_bytes(
            file_bytes=content,
            filename=filename,
            metadata_overrides=overrides,
            overwrite=overwrite,
        )

        # 入库成功后通知 QueryService 刷新检索索引
        if result.status in ("created", "overwritten") and self._on_ingested:
            self._on_ingested()

        return result

    def ingest_batch(
        self, dir_path: Path | None = None, overwrite: bool = False
    ) -> BatchIngestResult:
        """CLI 批量导入入口。"""
        target = Path(dir_path) if dir_path else self.archive_dir
        logger.info(f"Starting batch ingest from {target}")
        return self.pipeline.ingest_directory(target, overwrite=overwrite)
