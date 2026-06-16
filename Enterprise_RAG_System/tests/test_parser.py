import pytest
from pathlib import Path
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


class TestGetParser:
    def test_get_parser_by_extension(self):
        assert isinstance(get_parser("file.txt"), TxtParser)
        assert isinstance(get_parser("file.md"), MarkdownParser)

    def test_get_parser_unknown_extension(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_parser("file.xyz")
