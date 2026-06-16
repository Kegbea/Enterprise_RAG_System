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


class TestGetParser:
    def test_get_parser_by_extension(self):
        assert isinstance(get_parser("file.txt"), TxtParser)
        assert isinstance(get_parser("file.md"), MarkdownParser)

    def test_get_parser_unknown_extension(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            get_parser("file.xyz")
