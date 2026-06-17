"""查询服务 — 管理 RAG 引擎生命周期，供 API 路由层调用。

职责：
- 包装 HybridRetriever + Reranker + QueryEngine 的创建和更新
- 文档变更后自动刷新检索索引
- 暴露统一的 async query_stream() 接口

设计：
    引擎采用延迟初始化（lazy init）策略——只有首次查询或 refresh 时才构建索引。
    这避免了启动时无文档或 API key 无效导致的崩溃。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from app.etl.pipeline import InMemoryDocStore

logger = logging.getLogger(__name__)


class QueryService:
    """RAG 查询服务 — 管理检索引擎的单例服务。

    Usage:
        store = InMemoryDocStore(persist_dir="data/storage")
        query_service = QueryService(store)
        async for sse_event in query_service.query_stream("什么是 RAG？"):
            yield sse_event
    """

    def __init__(self, store: InMemoryDocStore):
        self._store = store
        self._retriever = None   # HybridRetriever
        self._reranker = None    # Reranker
        self._engine = None      # QueryEngine

    # ── 公开接口 ────────────────────────────────────────

    @property
    def ready(self) -> bool:
        """RAG 引擎是否已就绪（即是否有已索引的文档）。"""
        return self._engine is not None

    def ensure_ready(self) -> bool:
        """确保引擎已初始化，失败时返回 False。"""
        if self._engine is None:
            self._init_engine()
        return self._engine is not None

    async def query_stream(
        self, query: str, chat_history: list[dict[str, str]] | None = None
    ) -> AsyncGenerator[str, None]:
        """SSE 流式查询入口。

        Args:
            query: 用户问题
            chat_history: 可选对话历史

        Yields:
            SSE 事件字符串

        Raises:
            RuntimeError: 引擎未初始化（无文档）
        """
        if not self.ensure_ready():
            if self._store.count() == 0:
                raise RuntimeError(
                    "无文档：请先上传文档。POST /api/documents/upload"
                )
            raise RuntimeError(
                "RAG 引擎初始化失败：请检查 DASHSCOPE_API_KEY 配置是否正确。"
            )

        async for event in self._engine.query_stream(query, chat_history):
            yield event

    def refresh(self) -> None:
        """文档库变更后刷新检索索引。

        在 IngestionService 每次成功入库后调用。
        """
        nodes = self._store.get_all_nodes()
        if not nodes:
            logger.info("Store is empty, skipping index refresh")
            return
        if self._retriever is not None:
            try:
                self._retriever.refresh(nodes)
                logger.info(f"Retriever refreshed with {len(nodes)} nodes")
            except Exception as e:
                logger.warning(f"Failed to refresh retriever: {e}")
        else:
            self._init_engine()

    # ── 内部方法 ────────────────────────────────────────

    def _init_engine(self) -> None:
        """延迟初始化 RAG 检索全链路组件。"""
        nodes = self._store.get_all_nodes()
        if not nodes:
            logger.warning("No nodes in store, skipping RAG engine init")
            return

        try:
            from app.rag.hybrid_retriever import HybridRetriever
            from app.rag.query_engine import QueryEngine
            from app.rag.reranker import Reranker

            logger.info(f"Initializing RAG engine with {len(nodes)} nodes...")
            self._retriever = HybridRetriever(nodes)
            self._reranker = Reranker()
            self._engine = QueryEngine(self._retriever, self._reranker)
            logger.info("RAG engine initialized")
        except Exception as e:
            logger.error(f"Failed to initialize RAG engine: {e}")
            # 引擎保持 None，下次查询时重试
