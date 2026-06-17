"""混合检索器 — BM25(中文分词) + Dense(向量) + RRF 融合。

检索链路：
1. BM25Retriever（jieba 分词，关键词匹配）
2. VectorIndexRetriever（DashScope embedding，语义匹配）
3. RRF 融合排序 → top_k 候选节点

设计要点：
- BM25 tokenizer 必须显式传入 jieba 分词函数，否则默认英文分词器对中文无效
- RRF k 参数在 LlamaIndex 内部固定为 60（业界标准值）
- 检索结果保留原始 metadata（filename、page_number、heading_path 等），供前端引用卡片使用
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import jieba
from llama_index.core.indices.vector_store import VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.embeddings.dashscope import DashScopeEmbedding
from llama_index.llms.dashscope import DashScope
from llama_index.retrievers.bm25 import BM25Retriever

from app.config import settings

logger = logging.getLogger(__name__)


def chinese_tokenizer(text: str) -> list[str]:
    """jieba 中文分词器，BM25 专用。

    LlamaIndex BM25 默认使用英文正则分词 (?u)\\b\\w\\w+\\b，
    对中文完全无效。必须显式传入此函数。
    """
    return list(jieba.cut(text))


class HybridRetriever:
    """BM25 + Dense 混合检索器，RRF 融合排序。

    Usage:
        nodes = store.get_all_nodes()
        retriever = HybridRetriever(nodes)
        results = retriever.retrieve("什么是混合检索？")
    """

    def __init__(
        self,
        nodes: list[TextNode],
        dense_top_k: int | None = None,
        bm25_top_k: int | None = None,
        fusion_top_k: int | None = None,
        tokenizer: Callable[[str], list[str]] | None = None,
        embedding_model: str | None = None,
    ):
        """初始化混合检索器。

        Args:
            nodes: 全部文档节点（来自 InMemoryDocStore.get_all_nodes()）
            dense_top_k: Dense 检索召回数，默认 settings.hybrid_top_k (15)
            bm25_top_k: BM25 检索召回数，默认 settings.hybrid_top_k (15)
            fusion_top_k: RRF 融合后返回数，默认 settings.hybrid_top_k (15)
            tokenizer: BM25 分词函数，默认 jieba
            embedding_model: embedding 模型名，默认 settings.embedding_model
        """
        if not nodes:
            raise ValueError("Cannot build HybridRetriever with empty nodes list")

        self._nodes = nodes
        self._dense_top_k = dense_top_k or settings.hybrid_top_k
        self._bm25_top_k = bm25_top_k or settings.hybrid_top_k
        self._fusion_top_k = fusion_top_k or settings.hybrid_top_k
        self._tokenizer = tokenizer or chinese_tokenizer

        self._embed_model = DashScopeEmbedding(
            model_name=embedding_model or settings.embedding_model,
            api_key=settings.dashscope_api_key,
            embed_batch_size=settings.embed_batch_size,
        )
        # 创建一次 LLM 实例，供 _build_retrievers() 和 refresh() 复用
        self._fusion_llm = DashScope(
            model_name=settings.llm_model,
            api_key=settings.dashscope_api_key,
        )
        self._build_retrievers()

        logger.info(
            f"HybridRetriever ready: {len(nodes)} nodes, "
            f"dense_top_k={self._dense_top_k}, bm25_top_k={self._bm25_top_k}, "
            f"fusion_top_k={self._fusion_top_k}"
        )

    # ── 公开接口 ────────────────────────────────────────

    def retrieve(self, query: str) -> list[NodeWithScore]:
        """执行混合检索，返回 RRF 融合排序后的节点列表。"""
        results = self._fusion_retriever.retrieve(query)
        logger.debug(
            f"Hybrid retrieval for '{query[:50]}...' → {len(results)} results"
        )
        return results

    async def aretrieve(self, query: str) -> list[NodeWithScore]:
        """异步版本 — 在线程池中执行同步检索，避免阻塞事件循环。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.retrieve, query)

    def refresh(self, nodes: list[TextNode]) -> None:
        """文档库变更后刷新索引。

        Args:
            nodes: 更新后的全部节点列表
        """
        if not nodes:
            logger.warning("refresh() called with empty nodes, skipping")
            return

        self._nodes = nodes
        self._build_retrievers()
        logger.info(f"HybridRetriever refreshed with {len(nodes)} nodes")

    # ── 内部方法 ────────────────────────────────────────

    def _build_retrievers(self) -> None:
        """构建/重建 BM25 + Dense + RRF 检索器链路。

        提取为独立方法，供 __init__ 和 refresh() 复用。
        """
        self._bm25_retriever = BM25Retriever.from_defaults(
            nodes=self._nodes,
            tokenizer=self._tokenizer,
            similarity_top_k=self._bm25_top_k,
        )

        logger.info(f"Building dense index for {len(self._nodes)} nodes...")
        self._vector_index = VectorStoreIndex(
            nodes=self._nodes,
            embed_model=self._embed_model,
            show_progress=True,
        )
        self._dense_retriever = self._vector_index.as_retriever(
            similarity_top_k=self._dense_top_k
        )

        # RRF 融合需要传 LLM（用于 query generation，但 num_queries=1 时不生成）。
        # 如果不传，LlamaIndex 会回退到全局 Settings.llm（默认 OpenAI），
        # 导致检查 OPENAI_API_KEY 而报错。
        self._fusion_retriever = QueryFusionRetriever(
            retrievers=[self._bm25_retriever, self._dense_retriever],
            llm=self._fusion_llm,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=self._fusion_top_k,
            num_queries=1,
            use_async=False,
        )
