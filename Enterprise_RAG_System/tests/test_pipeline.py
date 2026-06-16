import pytest
from pathlib import Path
from app.etl.pipeline import ETLPipeline, InMemoryDocStore, IngestResult, BatchIngestResult
from app.models.document import DocumentMetadata


@pytest.fixture
def doc_store():
    return InMemoryDocStore()


class TestIngestResult:
    def test_ingest_result_created(self):
        result = IngestResult(filename="test.txt", status="created", chunks_created=5)
        assert result.status == "created"
        assert result.chunks_created == 5

    def test_ingest_result_skipped(self):
        result = IngestResult(filename="test.txt", status="skipped", checksum="abc123")
        assert result.status == "skipped"


class TestBatchIngestResult:
    def test_summary(self):
        items = [
            IngestResult(filename="a.txt", status="created", chunks_created=3),
            IngestResult(filename="b.pdf", status="skipped"),
            IngestResult(filename="c.docx", status="error", error_message="corrupt"),
        ]
        batch = BatchIngestResult(
            total=3, succeeded=1, skipped=1, failed=1, items=items,
        )
        assert batch.total == 3
        assert batch.succeeded == 1


class TestInMemoryDocStore:
    def test_add_and_count(self):
        store = InMemoryDocStore()
        store.add(ids=["1", "2"], documents=["a", "b"], metadatas=[{"x": 1}, {"x": 2}])
        assert store.count() == 2

    def test_get_by_metadata(self):
        store = InMemoryDocStore()
        store.add(ids=["1"], documents=["a"], metadatas=[{"checksum": "abc"}])
        result = store.get(where={"checksum": "abc"})
        assert "1" in result["ids"]

    def test_get_missing(self):
        store = InMemoryDocStore()
        result = store.get(where={"checksum": "nonexistent"})
        assert result["ids"] == []

    def test_delete(self):
        store = InMemoryDocStore()
        store.add(ids=["1", "2"], documents=["a", "b"], metadatas=[{}, {}])
        store.delete(ids=["1"])
        assert store.count() == 1


class TestETLPipeline:
    def test_ingest_txt_bytes(self, doc_store):
        """完整链路：TXT bytes → 解析 → 清洗 → 切块 → 入库。"""
        pipeline = ETLPipeline(doc_store)
        content = "企业知识管理系统。\n\n系统支持多种文档格式。" * 20
        result = pipeline.ingest_bytes(
            file_bytes=content.encode("utf-8"),
            filename="test.txt",
        )

        assert result.status == "created"
        assert result.chunks_created > 0
        assert result.checksum != ""
        assert result.duration_ms >= 0
        assert doc_store.count() > 0

    def test_ingest_duplicate_skip(self, doc_store):
        """相同文件重复上传应跳过。"""
        pipeline = ETLPipeline(doc_store)
        content = b"unique content for dedup test"

        result1 = pipeline.ingest_bytes(content, "dedup.txt")
        assert result1.status == "created"

        result2 = pipeline.ingest_bytes(content, "dedup.txt", overwrite=False)
        assert result2.status == "skipped"

    def test_ingest_duplicate_overwrite(self, doc_store):
        """overwrite=True 时应覆盖旧数据。"""
        pipeline = ETLPipeline(doc_store)
        content = b"content for overwrite test"

        result1 = pipeline.ingest_bytes(content, "overwrite.txt")
        assert result1.status == "created"

        result2 = pipeline.ingest_bytes(content, "overwrite.txt", overwrite=True)
        assert result2.status == "overwritten"

    def test_ingest_unsupported_type(self, doc_store):
        """不支持的文件类型应返回 error。"""
        pipeline = ETLPipeline(doc_store)
        result = pipeline.ingest_bytes(b"data", "file.xyz")
        assert result.status == "error"
        assert "unsupported" in result.error_message.lower()

    def test_ingest_with_metadata_overrides(self, doc_store):
        """metadata_overrides 应覆盖默认元数据。"""
        pipeline = ETLPipeline(doc_store)
        overrides = DocumentMetadata(
            filename="财务报告.txt",
            department_id="finance",
            tags=["财报"],
            custom_metadata={"项目": "PRJ-001"},
            source="cli",
        )
        content = "财务数据测试内容。" * 30
        result = pipeline.ingest_bytes(
            content.encode("utf-8"),
            filename="财务报告.txt",
            metadata_overrides=overrides,
        )
        assert result.status == "created"
