"""文档解析器 — 统一接口 + 四类格式实现 + 工厂函数。

设计原则：
- 所有解析器返回统一的 ParsedPage 结构
- 表格统一输出为 Markdown Table 格式
- 通过 get_parser() 工厂函数按扩展名分发
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re


@dataclass
class ParsedPage:
    """解析后的单页结构。

    表格统一为 Markdown Table 字符串，Chunker 只需识别一种格式。
    """

    page_number: int | None  # TXT/MD 为 None
    text: str = ""
    tables: list[str] = field(default_factory=list)  # Markdown table 格式
    headings: list[str] = field(default_factory=list)  # 该页检测到的标题


class BaseParser(ABC):
    """文档解析器基类。"""

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        """将文件字节流解析为 ParsedPage 列表。"""
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """返回支持的文件扩展名列表（不含点号）。"""
        ...


class TxtParser(BaseParser):
    """纯文本解析器 — 全文作为单页，无页码，无表格。"""

    def supported_extensions(self) -> list[str]:
        return ["txt"]

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        text = file_bytes.decode("utf-8", errors="replace")
        return [ParsedPage(page_number=None, text=text)]


class MarkdownParser(BaseParser):
    """Markdown 解析器 — 识别 # 标题层级，正则提取表格。"""

    def supported_extensions(self) -> list[str]:
        return ["md"]

    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        text = file_bytes.decode("utf-8", errors="replace")
        headings = self._extract_headings(text)
        tables = self._extract_tables(text)
        return [ParsedPage(page_number=None, text=text, tables=tables, headings=headings)]

    @staticmethod
    def _extract_headings(text: str) -> list[str]:
        headings = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                headings.append(heading)
        return headings

    @staticmethod
    def _extract_tables(text: str) -> list[str]:
        """提取 Markdown 表格（以 | 开头的连续行，含分隔行）。"""
        tables = []
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("|") and "---" not in line:
                if i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i + 1].strip()):
                    table_lines = [lines[i]]
                    i += 1
                    while i < len(lines):
                        table_lines.append(lines[i])
                        if i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
                            i += 1
                        else:
                            break
                    tables.append("\n".join(table_lines))
            i += 1
        return tables


# ── 解析器注册表 ──
_PARSER_REGISTRY: dict[str, BaseParser] = {}


def _register(parser: BaseParser) -> BaseParser:
    for ext in parser.supported_extensions():
        _PARSER_REGISTRY[ext] = parser
    return parser


# ── 注册内置解析器 ──
_register(TxtParser())
_register(MarkdownParser())


def get_parser(filename: str) -> BaseParser:
    """根据文件名扩展名获取对应的解析器实例。

    Raises:
        ValueError: 不支持的文件类型
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    parser = _PARSER_REGISTRY.get(ext)
    if parser is None:
        raise ValueError(f"Unsupported file type: .{ext}")
    return parser
