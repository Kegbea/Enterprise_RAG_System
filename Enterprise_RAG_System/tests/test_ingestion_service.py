import pytest
from pathlib import Path
from io import BytesIO
from app.etl.pipeline import ETLPipeline, InMemoryDocStore
from app.services.ingestion import IngestionService


class TestIngestionService:
    def test_ingest_upload_txt(self, tmp_path):
        """测试 API 上传入口：UploadFile → 入库。"""
        store = InMemoryDocStore()
        pipeline = ETLPipeline(store)
        service = IngestionService(pipeline, archive_dir=tmp_path)

        content = "企业知识管理系统测试内容。".encode("utf-8") * 20

        class FakeUploadFile:
            filename = "test.txt"
            file = BytesIO(content)

            async def read(self):
                return content

        result = service.ingest_upload_sync(
            FakeUploadFile(),
            department_id="engineering",
            tags=["测试"],
        )
        assert result.status == "created"
        assert result.chunks_created > 0

    def test_ingest_upload_with_custom_metadata(self, tmp_path):
        """上传时附带自定义标签和元数据。"""
        store = InMemoryDocStore()
        pipeline = ETLPipeline(store)
        service = IngestionService(pipeline, archive_dir=tmp_path)

        content = b"custom metadata test content" * 10

        class FakeUploadFile:
            filename = "custom.txt"
            file = BytesIO(content)

            async def read(self):
                return content

        result = service.ingest_upload_sync(
            FakeUploadFile(),
            tags=["重要", "内部"],
            custom_metadata={"作者": "张三", "版本": "v2.0"},
        )
        assert result.status == "created"

    def test_ingest_batch(self, tmp_path):
        """批量导入目录下的文件。"""
        (tmp_path / "doc1.txt").write_text("测试文档1内容。" * 20, encoding="utf-8")
        (tmp_path / "doc2.txt").write_text("测试文档2内容。" * 20, encoding="utf-8")

        store = InMemoryDocStore()
        pipeline = ETLPipeline(store)
        service = IngestionService(pipeline, archive_dir=tmp_path)
        batch = service.ingest_batch(tmp_path)

        assert batch.total >= 2
        assert batch.succeeded >= 2
        assert batch.failed == 0
