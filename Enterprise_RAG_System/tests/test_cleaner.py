import pytest
from app.etl.parser import ParsedPage
from app.etl.cleaner import TextCleaner


class TestTextCleaner:
    def setup_method(self):
        self.cleaner = TextCleaner()

    def test_normalize_fullwidth_to_halfwidth(self):
        """全角英文字母→半角，全角数字→半角。"""
        pages = [ParsedPage(page_number=1, text="ＡＢＣａｂｃ１２３")]
        result = self.cleaner.clean(pages)
        assert "ABCabc123" in result[0].text

    def test_collapse_whitespace(self):
        """多余空白压缩为单个空格。"""
        pages = [ParsedPage(page_number=1, text="hello    world  \n\n\n  foo")]
        result = self.cleaner.clean(pages)
        assert "hello world" in result[0].text
        assert "foo" in result[0].text

    def test_filter_control_chars(self):
        """滤除不可见控制字符。"""
        pages = [ParsedPage(page_number=1, text="正常文本\x00\x01\x02正常")]
        result = self.cleaner.clean(pages)
        assert "\x00" not in result[0].text
        assert "正常文本" in result[0].text

    def test_filter_empty_pages(self):
        """移除无文本且无表格的页。"""
        pages = [
            ParsedPage(page_number=1, text="", tables=[], headings=[]),
            ParsedPage(page_number=2, text="Valid content", tables=[], headings=[]),
            ParsedPage(page_number=3, text="", tables=["| a | b |"], headings=[]),
        ]
        result = self.cleaner.clean(pages)
        assert len(result) == 2
        assert result[0].page_number == 2
        assert result[1].page_number == 3

    def test_clean_table_cells(self):
        """表格单元格去除多余空格。"""
        pages = [ParsedPage(
            page_number=1,
            text="text",
            tables=["|  col1  |  col2  |\n|---|---|\n|  val1  |  val2  |"],
        )]
        result = self.cleaner.clean(pages)
        assert "| col1 | col2 |" in result[0].tables[0]

    def test_preserve_chinese_text(self):
        """中文文本保持不变。"""
        pages = [ParsedPage(page_number=1, text="企业知识管理系统 — 产品概述")]
        result = self.cleaner.clean(pages)
        assert "企业知识管理系统" in result[0].text
