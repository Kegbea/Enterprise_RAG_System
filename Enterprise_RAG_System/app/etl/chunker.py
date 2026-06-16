"""表格感知切块器 — 表格原子保留 + Parent-Child Node 构建。

核心设计：
1. 按 [TABLE:N] 占位符分割页面文本 → 表格段 / 文本段
2. 表格段作为原子 Node（不参与 chunk_size 切分），chunk_type=table
3. 文本段按语义边界切分（段落 > 句号 > 硬截断）
4. 每页构建一个 Parent Node（整页文本），关联所有子 Node
5. 检索时命中子 Node → 自动拉取 Parent → 返回完整上下文
"""

import logging
import re
from dataclasses import dataclass
from uuid import uuid4
from llama_index.core.schema import TextNode, NodeRelationship, RelatedNodeInfo
from app.etl.parser import ParsedPage
from app.models.document import DocumentMetadata, ChunkType

logger = logging.getLogger(__name__)


@dataclass
class ChunkConfig:
    chunk_size: int = 512
    chunk_overlap: int = 50
    max_table_rows: int = 50


class TableAwareChunker:
    """表格感知切块器 — 表格原子保留 + Parent-Child 树。"""

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    def chunk(
        self, pages: list[ParsedPage], base_metadata: DocumentMetadata
    ) -> list[TextNode]:
        all_nodes = []

        for page in pages:
            child_nodes = []
            segments = self._split_by_table_placeholder(page)

            for seg_type, seg_text, table_idx in segments:
                if seg_type == "table":
                    if table_idx is not None and table_idx < len(page.tables):
                        node = self._create_table_node(
                            page.tables[table_idx], page, base_metadata
                        )
                        child_nodes.append(node)
                else:
                    sub_texts = self._split_text(seg_text)
                    for sub in sub_texts:
                        node = self._create_text_node(sub, page, base_metadata)
                        child_nodes.append(node)

            if child_nodes:
                parent = self._create_parent_node(page, child_nodes, base_metadata)
                all_nodes.append(parent)
                all_nodes.extend(child_nodes)

        return all_nodes

    def _split_by_table_placeholder(
        self, page: ParsedPage
    ) -> list[tuple[str, str, int | None]]:
        """按 [TABLE:N] 占位符分割文本，返回 (type, text, table_index) 段列表。"""
        pattern = re.compile(r'\[TABLE:(\d+)\]')
        parts = pattern.split(page.text)
        segments = []
        for i, part in enumerate(parts):
            if i == 0:
                if part.strip():
                    segments.append(("text", part, None))
            elif re.match(r'^\d+$', part):
                idx = int(part)
                if idx < len(page.tables):
                    segments.append(("table", "", idx))
            else:
                if part.strip():
                    segments.append(("text", part, None))
        return segments

    def _split_text(self, text: str) -> list[str]:
        """按语义边界切分文本：段落 > 句号 > 硬截断。"""
        if len(text) <= self.config.chunk_size:
            return [text.strip()] if text.strip() else []

        chunks = []
        current = ""
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            if len(current) + len(para) <= self.config.chunk_size:
                current += ("\n\n" if current else "") + para
            else:
                if current.strip():
                    chunks.append(current.strip())
                if len(para) > self.config.chunk_size:
                    chunks.extend(self._split_by_sentence(para))
                else:
                    current = para
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _split_by_sentence(self, text: str) -> list[str]:
        """在句号/换行处切分长文本，最后硬截断兜底。"""
        sentences = re.split(r'(?<=[。！？\n])', text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) <= self.config.chunk_size:
                current += sent
            else:
                if current.strip():
                    chunks.append(current.strip())
                current = sent
        if current.strip():
            chunks.append(current.strip())

        final = []
        for chunk in chunks:
            if len(chunk) > self.config.chunk_size:
                start = 0
                while start < len(chunk):
                    end = min(start + self.config.chunk_size, len(chunk))
                    final.append(chunk[start:end])
                    start = end - self.config.chunk_overlap
            else:
                final.append(chunk)
        return final

    def _create_text_node(
        self, text: str, page: ParsedPage, base_meta: DocumentMetadata
    ) -> TextNode:
        node_id = str(uuid4())
        meta = self._build_metadata(base_meta, page, ChunkType.TEXT)
        return TextNode(id_=node_id, text=text, metadata=meta)

    def _create_table_node(
        self, table_md: str, page: ParsedPage, base_meta: DocumentMetadata
    ) -> TextNode:
        row_count = len([l for l in table_md.split("\n") if l.strip().startswith("|")])
        if row_count > self.config.max_table_rows:
            logger.warning(
                f"Table in {base_meta.filename} page {page.page_number} "
                f"has {row_count} rows (> {self.config.max_table_rows}), keeping atomic"
            )
        node_id = str(uuid4())
        meta = self._build_metadata(base_meta, page, ChunkType.TABLE)
        return TextNode(id_=node_id, text=table_md, metadata=meta)

    def _create_parent_node(
        self, page: ParsedPage, children: list[TextNode], base_meta: DocumentMetadata
    ) -> TextNode:
        parent_id = str(uuid4())
        meta = self._build_metadata(base_meta, page, ChunkType.TEXT)
        parent = TextNode(id_=parent_id, text=page.text, metadata=meta)
        parent.relationships[NodeRelationship.CHILD] = [
            RelatedNodeInfo(node_id=c.node_id) for c in children
        ]
        for child in children:
            child.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(
                node_id=parent_id
            )
        return parent

    @staticmethod
    def _build_metadata(
        base: DocumentMetadata, page: ParsedPage, chunk_type: ChunkType
    ) -> dict:
        return {
            "filename": base.filename,
            "page_number": page.page_number,
            "heading_path": (
                " > ".join(page.headings) if page.headings else base.heading_path
            ),
            "chunk_type": chunk_type.value,
            "department_id": base.department_id,
            "source": base.source,
            "file_type": base.file_type,
            "file_size": base.file_size,
            "checksum": base.checksum,
            "status": base.status.value,
            "tags": ",".join(base.tags),
            **base.custom_metadata,
        }
