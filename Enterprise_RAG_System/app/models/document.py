# app/models/document.py
import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"
    LIST = "list"
    CODE = "code"
    IMAGE_CAPTION = "image_caption"


class DocStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class DocumentMetadata(BaseModel):
    """企业级文档元数据 Schema — 每个 chunk 一份。"""

    model_config = {"extra": "forbid"}

    # ── 基础字段 ──
    filename: str
    page_number: int | None = None
    heading_path: str = ""
    chunk_type: ChunkType = ChunkType.TEXT

    # ── 安全与权限 ──
    department_id: str = "public"

    # ── 工业运维字段 ──
    source: str = "api"
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    file_type: str = ""
    file_size: int = 0
    checksum: str = ""
    status: DocStatus = DocStatus.ACTIVE

    # ── 业务扩展 ──
    tags: list[str] = Field(default_factory=list)
    custom_metadata: dict[str, str] = Field(default_factory=dict)

    @staticmethod
    def compute_checksum(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @model_validator(mode="after")
    def _default_file_type_from_filename(self):
        if not self.file_type and self.filename:
            ext = ""
            if "." in self.filename:
                ext = self.filename.rsplit(".", 1)[-1].lower()
            type_map = {"pdf": "pdf", "docx": "docx", "md": "md", "txt": "txt"}
            self.file_type = type_map.get(ext, "unknown")
        return self
