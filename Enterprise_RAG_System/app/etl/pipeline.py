"""ETL 编排器 — parser → cleaner → chunker → 向量存储。

职责：串起解析、清洗、切块、入库四个步骤，提供单文件和批量入口。
去重逻辑基于 SHA256 checksum，支持跳过或覆盖。

向量存储：当前使用内存存储（InMemoryDocStore），后续可切换 ChromaDB。
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.etl.chunker import ChunkConfig, TableAwareChunker
from app.etl.cleaner import TextCleaner
from app.etl.parser import get_parser
from app.models.document import DocumentMetadata

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """单文件入库结果。"""
    filename: str
    status: str = ""          # "created" | "skipped" | "overwritten" | "error"
    chunks_created: int = 0
    checksum: str = ""
    error_message: str = ""
    duration_ms: float = 0.0


@dataclass
class BatchIngestResult:
    """批量入库结果汇总。"""
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    overwritten: int = 0
    failed: int = 0
    items: list[IngestResult] = field(default_factory=list)


class InMemoryDocStore:
    """内存文档存储 — 简单的 dict 实现，用于开发/测试阶段。

    接口与 ChromaDB 兼容，后续可无缝切换：
    - add(ids, documents, metadatas)
    - get(where)
    - delete(ids)
    - count()
    """

    def __init__(self):
        self._docs: dict[str, dict] = {}

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        for id_, doc, meta in zip(ids, documents, metadatas):
            self._docs[id_] = {"document": doc, "metadata": meta}

    def get(self, where: dict) -> dict:
        """按 metadata 字段过滤。返回 ChromaDB 兼容格式。"""
        results = []
        key = list(where.keys())[0]
        value = where[key]
        for id_, entry in self._docs.items():
            if entry["metadata"].get(key) == value:
                results.append(id_)
        return {"ids": results}

    def delete(self, ids: list[str]) -> None:
        for id_ in ids:
            self._docs.pop(id_, None)

    def count(self) -> int:
        return len(self._docs)


class ETLPipeline:
    """ETL 编排器 — parser → cleaner → chunker → 向量存储。"""

    SUPPORTED_EXTENSIONS = {"pdf", "docx", "md", "txt"}

    def __init__(
        self,
        store: InMemoryDocStore | None = None,
        chunk_config: ChunkConfig | None = None,
    ):
        self.store = store or InMemoryDocStore()
        self.chunker = TableAwareChunker(chunk_config or ChunkConfig())
        self.cleaner = TextCleaner()

    def ingest_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        metadata_overrides: DocumentMetadata | None = None,
        overwrite: bool = False,
    ) -> IngestResult:
        start = time.perf_counter()

        # 1. 检查文件类型
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in self.SUPPORTED_EXTENSIONS:
            return IngestResult(
                filename=filename,
                status="error",
                error_message=f"Unsupported file type: .{ext}",
            )

        # 2. 计算 checksum + 去重检查
        checksum = DocumentMetadata.compute_checksum(file_bytes)
        existing = self.store.get(where={"checksum": checksum})
        if existing and existing["ids"]:
            if not overwrite:
                return IngestResult(
                    filename=filename,
                    status="skipped",
                    checksum=checksum,
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            else:
                self.store.delete(ids=existing["ids"])
                logger.info(
                    f"Overwriting {filename} ({len(existing['ids'])} old chunks removed)"
                )

        try:
            # 3. 解析
            parser = get_parser(filename)
            pages = parser.parse(file_bytes, filename)

            # 4. 清洗
            pages = self.cleaner.clean(pages)

            # 5. 构建元数据
            base_meta = metadata_overrides or DocumentMetadata(filename=filename)
            base_meta.checksum = checksum
            base_meta.file_size = len(file_bytes)
            base_meta.file_type = base_meta.file_type or ext

            # 6. 切块
            nodes = self.chunker.chunk(pages, base_meta)
            if not nodes:
                return IngestResult(
                    filename=filename,
                    status="error",
                    error_message="No content extracted (empty document?)",
                )

            # 7. 写入存储
            self._add_to_store(nodes)

            duration = (time.perf_counter() - start) * 1000
            status = "overwritten" if overwrite else "created"
            logger.info(
                f"Ingested {filename}: {len(nodes)} nodes, {duration:.0f}ms, status={status}"
            )

            return IngestResult(
                filename=filename,
                status=status,
                chunks_created=len(nodes),
                checksum=checksum,
                duration_ms=duration,
            )

        except Exception as e:
            logger.exception(f"Failed to ingest {filename}: {e}")
            return IngestResult(
                filename=filename,
                status="error",
                error_message=str(e),
                checksum=checksum,
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    def ingest_directory(
        self, dir_path: Path, overwrite: bool = False
    ) -> BatchIngestResult:
        batch = BatchIngestResult()
        files = []
        for ext in self.SUPPORTED_EXTENSIONS:
            files.extend(dir_path.rglob(f"*.{ext}"))

        batch.total = len(files)
        for file_path in sorted(files):
            try:
                file_bytes = file_path.read_bytes()
                result = self.ingest_bytes(file_bytes, file_path.name, overwrite=overwrite)
                batch.items.append(result)
                if result.status == "created":
                    batch.succeeded += 1
                elif result.status == "overwritten":
                    batch.overwritten += 1
                elif result.status == "skipped":
                    batch.skipped += 1
                else:
                    batch.failed += 1
            except Exception as e:
                batch.failed += 1
                batch.items.append(IngestResult(
                    filename=file_path.name,
                    status="error",
                    error_message=str(e),
                ))

        return batch

    def _add_to_store(self, nodes) -> None:
        """将 LlamaIndex TextNode 列表写入存储。"""
        ids = [n.node_id for n in nodes]
        texts = [n.text for n in nodes]
        metadatas = [n.metadata for n in nodes]
        self.store.add(ids=ids, documents=texts, metadatas=metadatas)
