import hashlib
import pytest
from datetime import datetime
from app.models.document import DocumentMetadata, ChunkType, DocStatus


class TestDocumentMetadata:
    def test_default_values(self):
        meta = DocumentMetadata(filename="report.pdf")
        assert meta.filename == "report.pdf"
        assert meta.page_number is None
        assert meta.heading_path == ""
        assert meta.chunk_type == ChunkType.TEXT
        assert meta.department_id == "public"
        assert meta.source == "api"
        assert meta.file_type == "pdf"  # auto-detected
        assert meta.file_size == 0
        assert meta.checksum == ""
        assert meta.status == DocStatus.ACTIVE
        assert meta.tags == []
        assert meta.custom_metadata == {}

    def test_file_type_auto_detection(self):
        cases = [
            ("report.pdf", "pdf"),
            ("memo.docx", "docx"),
            ("notes.md", "md"),
            ("readme.txt", "txt"),
            ("unknown.xyz", "unknown"),
            ("no_extension", "unknown"),
        ]
        for filename, expected in cases:
            meta = DocumentMetadata(filename=filename)
            assert meta.file_type == expected, f"{filename} -> {expected}"

    def test_explicit_file_type_overrides_auto(self):
        meta = DocumentMetadata(filename="data.bin", file_type="pdf")
        assert meta.file_type == "pdf"

    def test_compute_checksum(self):
        content = b"hello world"
        expected = hashlib.sha256(content).hexdigest()
        assert DocumentMetadata.compute_checksum(content) == expected

    def test_custom_metadata_and_tags(self):
        meta = DocumentMetadata(
            filename="财务报告2024.pdf",
            tags=["财报", "2024", "Q4"],
            custom_metadata={"项目编号": "PRJ-001", "密级": "内部"},
        )
        assert len(meta.tags) == 3
        assert meta.custom_metadata["项目编号"] == "PRJ-001"

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            DocumentMetadata(filename="x.pdf", unknown_field=123)
