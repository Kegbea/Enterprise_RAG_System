from app.etl.chunker import ChunkConfig, TableAwareChunker
from app.etl.parser import ParsedPage
from app.models.document import DocumentMetadata


class TestTableAwareChunker:
    def setup_method(self):
        self.config = ChunkConfig(chunk_size=512, chunk_overlap=50, max_table_rows=50)
        self.chunker = TableAwareChunker(self.config)

    def test_chunk_simple_text(self):
        """简单文本按 chunk_size 切分。"""
        pages = [ParsedPage(page_number=1, text="你好世界。" * 200)]
        base_meta = DocumentMetadata(filename="test.txt")
        nodes = self.chunker.chunk(pages, base_meta)

        assert len(nodes) > 0
        for node in nodes:
            assert node.metadata["filename"] == "test.txt"

    def test_table_atomic_preservation(self):
        """表格应作为原子 chunk 完整保留。"""
        table_md = "| A | B | C |\n|---|---|---|\n" + "\n".join(
            [f"| row{i} | data{i} | info{i} |" for i in range(10)]
        )
        pages = [ParsedPage(
            page_number=1,
            text="前言段落。\n[TABLE:0]\n后续段落。",
            tables=[table_md],
        )]
        base_meta = DocumentMetadata(filename="test.md")
        nodes = self.chunker.chunk(pages, base_meta)

        table_nodes = [n for n in nodes if n.metadata.get("chunk_type") == "table"]
        assert len(table_nodes) == 1
        assert "row0" in table_nodes[0].text
        assert "row9" in table_nodes[0].text
        assert "|---|---|" in table_nodes[0].text

    def test_parent_child_relationship(self):
        """Parent node 应关联 child nodes。"""
        pages = [ParsedPage(page_number=1, text="段落A。\n段落B。", tables=[])]
        base_meta = DocumentMetadata(filename="test.txt")
        nodes = self.chunker.chunk(pages, base_meta)

        from llama_index.core.schema import NodeRelationship
        children = [n for n in nodes if n.relationships.get(NodeRelationship.PARENT)]
        assert len(children) > 0

    def test_metadata_injection(self):
        """每个 node 应携带完整的元数据。"""
        pages = [ParsedPage(page_number=3, text="第3页内容。", tables=[], headings=["第1章"])]
        base_meta = DocumentMetadata(
            filename="报告.pdf",
            department_id="finance",
            tags=["财报"],
        )
        nodes = self.chunker.chunk(pages, base_meta)

        for node in nodes:
            assert node.metadata["filename"] == "报告.pdf"
            assert node.metadata["department_id"] == "finance"
            assert node.metadata["page_number"] == 3

    def test_semantic_boundary_split(self):
        """优先在句号处分段。"""
        text = "第一句话。第二句话。第三句话。" * 50
        pages = [ParsedPage(page_number=1, text=text)]
        base_meta = DocumentMetadata(filename="test.txt")
        nodes = self.chunker.chunk(pages, base_meta)

        from llama_index.core.schema import NodeRelationship
        children = [n for n in nodes if n.relationships.get(NodeRelationship.PARENT)]
        for child in children:
            assert child.text.strip().endswith(("。", "\n"))

    def test_empty_page_no_nodes(self):
        """空页不产生任何 node。"""
        pages = [ParsedPage(page_number=1, text="", tables=[])]
        base_meta = DocumentMetadata(filename="empty.txt")
        nodes = self.chunker.chunk(pages, base_meta)
        assert len(nodes) == 0
