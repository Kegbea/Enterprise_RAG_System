"""RAG 检索链路测试 — HybridRetriever / Reranker / QueryEngine。

测试策略：
- 不依赖有效 API key 的单元测试（BM25 分词、SSE 格式、数据结构等）
- API 相关测试用 skip 标记，需有效 DASHSCOPE_API_KEY 时手动运行
"""

import json
import os

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from app.rag.hybrid_retriever import chinese_tokenizer

# ── 中文分词测试 ────────────────────────────────────────


class TestChineseTokenizer:
    def test_tokenize_chinese(self):
        """中文分词应返回多个词条。"""
        tokens = chinese_tokenizer("企业知识管理系统")
        assert len(tokens) >= 3  # 企业/知识/管理/系统

    def test_tokenize_english(self):
        """混合中英文分词。"""
        tokens = chinese_tokenizer("RAG检索增强生成")
        assert "RAG" in tokens or any("RAG" in t for t in tokens)

    def test_tokenize_empty(self):
        """空字符串分词。"""
        tokens = chinese_tokenizer("")
        assert tokens == []


# ── SSE 事件格式测试 ─────────────────────────────────────


class TestSSEEventFormat:
    def test_token_event(self):
        """token 事件 SSE 格式。"""
        from app.rag.query_engine import _sse_event

        event = _sse_event("token", {"token": "你好"})
        assert 'event: token' in event
        assert 'data: ' in event
        data = json.loads(event.split("data: ")[1])
        assert data["token"] == "你好"

    def test_citation_event(self):
        """citation 事件 SSE 格式。"""
        from app.rag.query_engine import _sse_event

        data = {"sources": [{"filename": "test.pdf", "page_number": 1}]}
        event = _sse_event("citation", data)
        assert 'event: citation' in event
        parsed = json.loads(event.split("data: ")[1])
        assert parsed["sources"][0]["filename"] == "test.pdf"

    def test_done_event(self):
        """done 事件 SSE 格式。"""
        from app.rag.query_engine import _sse_event

        event = _sse_event("done", {"status": "complete", "token_count": 42})
        assert 'event: done' in event
        parsed = json.loads(event.split("data: ")[1])
        assert parsed["token_count"] == 42


# ── Citation 提取测试 ────────────────────────────────────


class TestCitationExtraction:
    def test_extract_from_nodes(self):
        """从 NodeWithScore 提取引用来源。"""
        from app.rag.query_engine import _extract_citations

        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_="n1",
                    text="文档内容A",
                    metadata={"filename": "a.pdf", "page_number": 1, "heading_path": "第一章"},
                ),
                score=0.9,
            ),
            NodeWithScore(
                node=TextNode(
                    id_="n2",
                    text="文档内容B",
                    metadata={"filename": "b.pdf", "page_number": 2},
                ),
                score=0.8,
            ),
        ]
        citations = _extract_citations(nodes)
        assert len(citations) == 2
        assert citations[0].filename == "a.pdf"
        assert citations[0].page_number == 1
        assert citations[0].heading_path == "第一章"
        assert citations[1].filename == "b.pdf"

    def test_deduplicate_same_source(self):
        """同一文件同一页应去重。"""
        from app.rag.query_engine import _extract_citations

        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_="n1", text="chunk1",
                    metadata={"filename": "a.pdf", "page_number": 1},
                ),
                score=0.9,
            ),
            NodeWithScore(
                node=TextNode(
                    id_="n2", text="chunk2",
                    metadata={"filename": "a.pdf", "page_number": 1},
                ),
                score=0.8,
            ),
        ]
        citations = _extract_citations(nodes)
        assert len(citations) == 1

    def test_snippet_truncation(self):
        """摘要截断到 200 字。"""
        from app.rag.query_engine import _extract_citations

        long_text = "长文本" * 150  # 450 chars
        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_="n1", text=long_text,
                    metadata={"filename": "a.pdf"},
                ),
                score=0.9,
            )
        ]
        citations = _extract_citations(nodes)
        assert len(citations[0].snippet) <= 200


# ── Context 构建测试 ─────────────────────────────────────


class TestContextBuilding:
    def test_build_context(self):
        """构建 LLM 上下文格式化。"""
        from app.rag.query_engine import _build_context

        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_="n1",
                    text="这是测试内容。",
                    metadata={"filename": "test.pdf", "page_number": 1, "heading_path": "概述"},
                ),
                score=0.9,
            ),
        ]
        context = _build_context(nodes)
        assert "[来源 1" in context
        assert "test.pdf" in context
        assert "第1页" in context
        assert "概述" in context
        assert "这是测试内容。" in context

    def test_build_context_without_page(self):
        """无页码时不显示页码信息。"""
        from app.rag.query_engine import _build_context

        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_="n1", text="内容",
                    metadata={"filename": "test.pdf"},
                ),
                score=0.9,
            ),
        ]
        context = _build_context(nodes)
        assert "第" not in context  # 无页码时不显示


# ── QueryResult 测试 ─────────────────────────────────────


class TestQueryResult:
    def test_default_values(self):
        from app.rag.query_engine import QueryResult

        result = QueryResult()
        assert result.answer == ""
        assert result.citations == []
        assert result.token_count == 0

    def test_citation_source_fields(self):
        from app.rag.query_engine import CitationSource

        c = CitationSource(
            filename="doc.pdf",
            page_number=3,
            heading_path="第一章 > 1.1",
            chunk_type="text",
            snippet="摘要...",
            node_id="abc123",
        )
        assert c.filename == "doc.pdf"
        assert c.page_number == 3
        assert c.chunk_type == "text"


# ── InMemoryDocStore 持久化测试 ──────────────────────────


class TestDocStorePersistence:
    def test_persist_and_restore(self, tmp_path):
        """持久化后重启恢复。"""
        from app.etl.pipeline import InMemoryDocStore

        store_dir = str(tmp_path / "store1")
        store1 = InMemoryDocStore(persist_dir=store_dir)
        store1.add(
            ids=["n1", "n2"],
            documents=["doc1", "doc2"],
            metadatas=[{"key": "a"}, {"key": "b"}],
        )
        store1.persist()

        # 模拟重启：创建新实例从同一目录恢复
        store2 = InMemoryDocStore(persist_dir=store_dir)
        assert store2.count() == 2
        result = store2.get(where={"key": "a"})
        assert len(result["ids"]) == 1

    def test_empty_store_restore(self, tmp_path):
        """空目录恢复应返回空 store。"""
        from app.etl.pipeline import InMemoryDocStore

        store_dir = str(tmp_path / "empty_store")
        store = InMemoryDocStore(persist_dir=store_dir)
        assert store.count() == 0

    def test_get_all_nodes(self, tmp_path):
        """get_all_nodes 应返回所有 TextNode。"""
        from app.etl.pipeline import InMemoryDocStore

        store = InMemoryDocStore()
        store.add(
            ids=["n1", "n2"],
            documents=["text1", "text2"],
            metadatas=[{"idx": 1}, {"idx": 2}],
        )
        nodes = store.get_all_nodes()
        assert len(nodes) == 2
        assert all(isinstance(n, TextNode) for n in nodes)
        texts = {n.text for n in nodes}
        assert texts == {"text1", "text2"}


# ── HybridRetriever 集成测试（需要有效 API key） ────────


@pytest.mark.skip(reason="需要有效的 DASHSCOPE_API_KEY，设置 RUN_RAG_TESTS=1 手动运行")
class TestHybridRetrieverIntegration:
    """需要有效 DASHSCOPE_API_KEY 的集成测试。"""

    def test_build_with_nodes(self):
        """用少量节点构建检索器。"""
        if not os.getenv("RUN_RAG_TESTS"):
            pytest.skip("Set RUN_RAG_TESTS=1 to run integration tests")

        from app.rag.hybrid_retriever import HybridRetriever

        nodes = [
            TextNode(
                id_=f"n{i}",
                text=f"这是第{i}个文档片段，用于测试混合检索功能。",
                metadata={"filename": f"doc{i}.txt", "page_number": i},
            )
            for i in range(3)
        ]
        retriever = HybridRetriever(nodes, dense_top_k=2, bm25_top_k=2, fusion_top_k=2)
        results = retriever.retrieve("混合检索")
        assert len(results) <= 2
        assert len(results) > 0


# ── Reranker 测试 ────────────────────────────────────────


class TestReranker:
    def test_init_passthrough_mode(self):
        """FlagEmbedding 不可用时降级为直通模式。"""
        from app.rag.reranker import Reranker

        reranker = Reranker(top_n=3)
        assert reranker._top_n == 3
        # 直通模式下 available 为 False
        # （FlagEmbedding 未安装时预期行为）

    def test_rerank_passthrough(self):
        """直通模式：截断返回前 top_n。"""
        from app.rag.reranker import Reranker

        reranker = Reranker(top_n=2)
        nodes = [
            NodeWithScore(
                node=TextNode(id_="n1", text="doc1", metadata={"filename": "a.txt"}),
                score=0.9,
            ),
            NodeWithScore(
                node=TextNode(id_="n2", text="doc2", metadata={"filename": "b.txt"}),
                score=0.8,
            ),
            NodeWithScore(
                node=TextNode(id_="n3", text="doc3", metadata={"filename": "c.txt"}),
                score=0.7,
            ),
        ]
        result = reranker.rerank("query", nodes)
        assert len(result) == 2
        assert result[0].node_id == "n1"
        assert result[1].node_id == "n2"

    def test_rerank_empty_list(self):
        """空列表返回空列表。"""
        from app.rag.reranker import Reranker

        reranker = Reranker(top_n=3)
        result = reranker.rerank("query", [])
        assert result == []


# ── QueryService 测试 ────────────────────────────────────


class TestQueryService:
    def test_init_empty_store(self, tmp_path):
        """空 store 初始化，引擎应保持 None（延迟初始化）。"""
        from app.etl.pipeline import InMemoryDocStore
        from app.services.query_service import QueryService

        store = InMemoryDocStore()
        qs = QueryService(store)
        assert qs.ready is False

    def test_init_with_data(self, tmp_path):
        """有数据的 store 初始化。"""
        from app.etl.pipeline import InMemoryDocStore
        from app.services.query_service import QueryService

        store = InMemoryDocStore()
        store.add(
            ids=["n1"],
            documents=["测试文档内容。"] * 3,
            metadatas=[{"filename": "test.txt"}] * 3,
        )
        # 有数据但 API key 无效，初始化应失败但不崩溃
        _qs = QueryService(store)
        # 引擎可能因 API key 无效而未初始化
        # 这是预期行为 — 不应崩溃
        assert _qs is not None  # QueryService 对象应成功创建

    def test_refresh_with_empty_store(self):
        """空 store 上调用 refresh 应跳过。"""
        from app.etl.pipeline import InMemoryDocStore
        from app.services.query_service import QueryService

        store = InMemoryDocStore()
        qs = QueryService(store)
        # 不应抛出异常
        qs.refresh()
        assert qs.ready is False

    def test_query_without_docs_raises(self):
        """无文档时查询应抛出 RuntimeError。"""
        from app.etl.pipeline import InMemoryDocStore
        from app.services.query_service import QueryService

        store = InMemoryDocStore()
        qs = QueryService(store)

        import asyncio

        async def _test():
            async for _ in qs.query_stream("test query"):
                pass

        with pytest.raises(RuntimeError, match="请先上传文档"):
            asyncio.run(_test())
