"""查询服务 — 管理 RAG 引擎生命周期，供 API 路由层调用。

职责：
- 包装 HybridRetriever + Reranker + QueryEngine 的创建和更新
- 文档变更后自动刷新检索索引
- 暴露统一的 async query_stream() 接口

设计：
    引擎采用延迟初始化（lazy init）策略——只有首次查询或 refresh 时才构建索引。
    这避免了启动时无文档或 API key 无效导致的崩溃。

    刷新操作通过 run_in_executor 在线程池中执行，避免阻塞事件循环。
    构建失败时保留原有引擎状态，不会导致 503。
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import AsyncGenerator

from app.etl.pipeline import InMemoryDocStore

logger = logging.getLogger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    """检测异常是否由 API 限流 (429) 引起。

    检查异常链中是否包含 429 / rate limit / throttl 等关键词。
    """
    msg = str(exc).lower()
    keywords = ("429", "rate limit", "throttl", "too many requests", "qps")
    return any(kw in msg for kw in keywords)


def _log_rebuild_done(task: asyncio.Task) -> None:
    """后台索引构建完成回调 — 记录异常（如有），避免静默失败。"""
    try:
        task.result()
    except Exception:
        logger.exception("Background index rebuild task failed (existing engine preserved)")
    else:
        logger.info("Background index rebuild completed successfully")


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
        self._rebuild_task: asyncio.Task | None = None  # 持有引用，防 GC

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

        由 IngestionService 在每次成功入库后同步调用。
        这里将耗时的索引构建操作在线程池中异步提交，不阻塞调用方。
        构建失败时保留原有引擎状态，不会导致服务降级到 503。
        """
        nodes = self._store.get_all_nodes()
        if not nodes:
            logger.info("Store is empty, skipping index refresh")
            return

        # 提交到默认线程池，异步构建索引
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环时（CLI/测试），同步构建
            self._build_index(nodes)
            return

        self._rebuild_task = loop.create_task(self._async_build(nodes))
        self._rebuild_task.add_done_callback(_log_rebuild_done)

    def refresh_sync(self) -> None:
        """同步刷新检索索引（CLI/测试使用）。"""
        nodes = self._store.get_all_nodes()
        if not nodes:
            logger.info("Store is empty, skipping index refresh")
            return
        self._build_index(nodes)

    # ── 内部方法 ────────────────────────────────────────

    async def _async_build(self, nodes) -> None:
        """异步构建索引 — 在线程池中执行，失败不影响现有引擎。"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._build_index, nodes)

    def _build_index(self, nodes) -> None:
        """在线程池中执行的同步索引构建逻辑。

        同时用于首次初始化（_init_engine）和后续刷新（refresh/refresh_sync）。

        关键设计：
        - 先构建新引擎，成功后再原子替换旧引擎
        - 遭遇 QPS 限流 (429) 时指数退避重试（1s→2s→4s→8s→16s）
        - 失败时保留原有状态，确保服务不会因一次刷新失败而降级
        """
        import time

        from app.config import settings

        last_error: Exception | None = None
        for attempt in range(settings.embed_max_retries):
            try:
                from app.rag.hybrid_retriever import HybridRetriever
                from app.rag.query_engine import QueryEngine
                from app.rag.reranker import Reranker

                logger.info(
                    f"Building RAG index with {len(nodes)} nodes "
                    f"(attempt {attempt + 1}/{settings.embed_max_retries})..."
                )

                # 先在临时变量中构建，成功后再原子替换
                new_retriever = HybridRetriever(nodes)
                new_reranker = Reranker()
                new_engine = QueryEngine(new_retriever, new_reranker)

                # 原子替换——只有全部成功后才更新
                self._retriever = new_retriever
                self._reranker = new_reranker
                self._engine = new_engine
                logger.info("RAG index built successfully")
                return  # 成功，立即返回

            except Exception as exc:
                last_error = exc
                is_rate_limit = _is_rate_limit_error(exc)

                if is_rate_limit and attempt < settings.embed_max_retries - 1:
                    delay = min(2 ** attempt, 30)  # 1, 2, 4, 8, 16, 30...
                    logger.warning(
                        f"Embedding rate limited (attempt {attempt + 1}/"
                        f"{settings.embed_max_retries}), retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    break  # 非限流错误或已达最大重试

        # 所有重试均失败
        if self._engine is not None:
            logger.exception(
                "Index build failed after %d attempts — "
                "existing engine preserved, service unaffected",
                settings.embed_max_retries,
            )
        else:
            logger.error(
                "Initial index build failed after %d attempts — "
                "engine remains None, clients will receive 503.\n"
                "Last error: %s\n%s",
                settings.embed_max_retries,
                last_error,
                traceback.format_exc(),
            )

    def _init_engine(self) -> None:
        """延迟初始化 RAG 检索全链路组件。"""
        nodes = self._store.get_all_nodes()
        if not nodes:
            logger.warning("No nodes in store, skipping RAG engine init")
            return

        self._build_index(nodes)
