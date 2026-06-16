"""文本清洗器 — 规范化 + 去噪 + 空页过滤。

职责单一：接收 ParsedPage 列表，产出清洗后的 ParsedPage 列表。
无状态，纯函数风格，可脱离 ETL 管道独立测试。
"""

import re

from app.etl.parser import ParsedPage


class TextCleaner:
    """文本清洗器 — 全角→半角，空白压缩，控制字符过滤，空页移除。"""

    # 全角→半角字符映射
    _FULLWIDTH_MAP = str.maketrans(
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
        "０１２３４５６７８９"
        "　",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        " ",
    )

    def clean(self, pages: list[ParsedPage]) -> list[ParsedPage]:
        cleaned = []
        for page in pages:
            text = self._normalize(page.text)
            tables = [self._normalize_table(t) for t in page.tables]
            if text.strip() or tables:
                cleaned.append(ParsedPage(
                    page_number=page.page_number,
                    text=text,
                    tables=tables,
                    headings=page.headings,
                ))
        return cleaned

    def _normalize(self, text: str) -> str:
        # 1. 全角→半角
        text = text.translate(self._FULLWIDTH_MAP)
        # 2. 滤除控制字符（保留换行 \n 和制表符 \t 用于后续分段）
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # 3. 多余空白压缩：>2个换行→2个换行，>1个空格→1个空格
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        # 4. 去除首尾空白
        text = text.strip()
        return text

    def _normalize_table(self, table: str) -> str:
        """清洗 Markdown Table 字符串 — 压缩单元格内多余空格。"""
        lines = table.split("\n")
        cleaned_lines = []
        for line in lines:
            if line.strip():
                # 按 | 分割，保留外围结构
                parts = line.split("|")
                # 去除每个单元格的首尾空格
                cells = [p.strip() for p in parts]
                cleaned_lines.append(" | ".join(cells))
        return "\n".join(cleaned_lines)
