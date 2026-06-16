import pytest
from pathlib import Path
from io import BytesIO
from docx import Document as DocxDocument
from app.etl.parser import ParsedPage, BaseParser, TxtParser, MarkdownParser, get_parser

FIXTURES = Path(__file__).parent / "fixtures"


class TestParsedPage:
    def test_create_parsed_page(self):
        page = ParsedPage(page_number=1, text="hello", tables=[], headings=[])
        assert page.page_number == 1
        assert page.text == "hello"
        assert page.tables == []
        assert page.headings == []


class TestTxtParser:
    def test_supported_extensions(self):
        parser = TxtParser()
        assert "txt" in parser.supported_extensions()

    def test_parse_txt_file(self):
        parser = TxtParser()
        file_bytes = (FIXTURES / "sample.txt").read_bytes()
        pages = parser.parse(file_bytes, "sample.txt")

        assert len(pages) >= 1
        assert all(isinstance(p, ParsedPage) for p in pages)
        assert pages[0].page_number is None
        assert "企业知识管理系统" in pages[0].text
        assert pages[0].tables == []

    def test_parse_empty_txt(self):
        parser = TxtParser()
        pages = parser.parse(b"", "empty.txt")
        assert len(pages) == 1
        assert pages[0].text == ""


class TestMarkdownParser:
    def test_supported_extensions(self):
        parser = MarkdownParser()
        assert "md" in parser.supported_extensions()

    def test_parse_md_headings(self):
        parser = MarkdownParser()
        file_bytes = (FIXTURES / "sample.md").read_bytes()
        pages = parser.parse(file_bytes, "sample.md")

        assert len(pages) >= 1
        assert pages[0].page_number is None
        assert len(pages[0].headings) > 0
        assert "企业知识管理系统" in " ".join(pages[0].headings)

    def test_parse_md_table(self):
        parser = MarkdownParser()
        file_bytes = (FIXTURES / "sample.md").read_bytes()
        pages = parser.parse(file_bytes, "sample.md")

        all_tables = [t for p in pages for t in p.tables]
        assert len(all_tables) >= 1
        assert "组件" in all_tables[0]
        assert "ChromaDB" in all_tables[0]

    def test_parse_md_heading_path(self):
        parser = MarkdownParser()
        content = b"# Ch1\n\n## Sec1.1\n\nSome text here.\n\n### Sec1.1.1\n\nDeeper text.\n"
        pages = parser.parse(content, "test.md")
        text = pages[0].text
        assert "Ch1" in text
        assert "Sec1.1" in text

    def test_md_no_table(self):
        parser = MarkdownParser()
        content = b"# Title\n\nJust some paragraph text.\n\nAnother paragraph.\n"
        pages = parser.parse(content, "test.md")
        assert pages[0].tables == []


def _make_docx_bytes(paragraphs: list[str], include_table: bool = False) -> bytes:
    """辅助函数：用 python-docx 生成最小 docx 文件 bytes。"""
    doc = DocxDocument()
    for text in paragraphs:
        doc.add_paragraph(text)
    if include_table:
        table = doc.add_table(rows=3, cols=3)
        table.style = "Table Grid"
        headers = ["列A", "列B", "列C"]
        for j, h in enumerate(headers):
            table.rows[0].cells[j].text = h
        data = [["val1", "val2", "val3"], ["val4", "val5", "val6"]]
        for i, row_data in enumerate(data):
            for j, val in enumerate(row_data):
                table.rows[i + 1].cells[j].text = val
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestDocxParser:
    def test_supported_extensions(self):
        from app.etl.parser import DocxParser
        parser = DocxParser()
        assert "docx" in parser.supported_extensions()

    def test_parse_docx_paragraphs(self):
        from app.etl.parser import DocxParser
        parser = DocxParser()
        file_bytes = _make_docx_bytes(["第一章 概述", "这是一段测试文本。", "这是第二段。"])
        pages = parser.parse(file_bytes, "test.docx")

        assert len(pages) == 1
        assert "第一章 概述" in pages[0].text
        assert "测试文本" in pages[0].text
        assert pages[0].page_number is None

    def test_parse_docx_with_table(self):
        from app.etl.parser import DocxParser
        parser = DocxParser()
        file_bytes = _make_docx_bytes(["以下是数据表格："], include_table=True)
        pages = parser.parse(file_bytes, "test.docx")

        assert len(pages[0].tables) >= 1
        assert "列A" in pages[0].tables[0]
        assert "val1" in pages[0].tables[0]

    def test_parse_empty_docx(self):
        from app.etl.parser import DocxParser
        parser = DocxParser()
        file_bytes = _make_docx_bytes([])
        pages = parser.parse(file_bytes, "empty.docx")
        assert len(pages) >= 1


class TestGetParser:
    def test_get_parser_by_extension(self):
        from app.etl.parser import DocxParser
        assert isinstance(get_parser("file.txt"), TxtParser)
        assert isinstance(get_parser("file.md"), MarkdownParser)
        assert isinstance(get_parser("file.docx"), DocxParser)

    def test_get_parser_unknown_extension(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_parser("file.xyz")
