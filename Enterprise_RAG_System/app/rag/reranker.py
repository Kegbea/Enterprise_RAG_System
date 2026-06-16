"""重排序器 — bge-reranker-v2-m3 本地模型封装。

在混合检索结果之上做精细重排序，提升 Top-K 结果的相关性。
首次运行自动从 HuggingFace 下载模型（约 1.1GB），后续使用本地缓存。

注意：FlagEmbedding 依赖 PyTorch，在部分 Windows 环境下可能因 DLL 冲突
无法加载。此时 Reranker 会降级为 pass-through 模式（不重排序直接返回）。
"""

from __future__ import annotations

import logging

from llama_index.core.schema import NodeWithScore, QueryBundle

from app.config import settings

logger = logging.getLogger(__name__)

# FlagEmbedding 可选依赖（依赖 PyTorch，部分 Windows 环境不兼容）
_FLAG_EMBEDDING_AVAILABLE = False
try:
    from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

    _FLAG_EMBEDDING_AVAILABLE = True
except ImportError as e:
    logger.warning(
        f"FlagEmbedding not available ({e}). "
        f"Reranker will operate in pass-through mode (no reranking). "
        f"To enable: pip install flagembedding"
    )


class Reranker:
    """bge-reranker-v2-m3 重排序器（FlagEmbedding 不可用时降级为直通模式）。

    Usage:
        reranker = Reranker()
        reranked = reranker.rerank(query, nodes)
    """

    def __init__(
        self,
        model: str | None = None,
        top_n: int | None = None,
        use_fp16: bool = False,
    ):
        """
        Args:
            model: HuggingFace 模型 ID，默认 settings.reranker_model
            top_n: 返回节点数，默认 settings.top_k (5)
            use_fp16: 是否使用半精度（CPU 环境通常不需要）
        """
        model_name = model or settings.reranker_model
        self._top_n = top_n or settings.top_k
        self._model = None

        if _FLAG_EMBEDDING_AVAILABLE:
            logger.info(f"Loading reranker model: {model_name} (top_n={self._top_n})")
            try:
                self._model = FlagEmbeddingReranker(
                    model=model_name,
                    top_n=self._top_n,
                    use_fp16=use_fp16,
                )
                logger.info("Reranker ready")
            except Exception as e:
                logger.warning(f"Failed to load reranker model: {e}. Using pass-through mode.")
        else:
            logger.info("Reranker in pass-through mode (FlagEmbedding not installed)")

    @property
    def available(self) -> bool:
        """FlagEmbedding 模型是否已成功加载。"""
        return self._model is not None

    def rerank(
        self,
        query: str | QueryBundle,
        nodes: list[NodeWithScore],
    ) -> list[NodeWithScore]:
        """对候选节点重排序，返回 Top-N。

        当 FlagEmbedding 不可用时，直接截断返回前 top_n 个节点（保持原排序）。

        Args:
            query: 查询字符串或 QueryBundle
            nodes: 候选节点列表（来自 HybridRetriever.retrieve()）

        Returns:
            重排序后的 Top-N 节点
        """
        if not nodes:
            return []

        if self._model is not None:
            if isinstance(query, str):
                return self._model.postprocess_nodes(nodes, query_str=query)
            return self._model.postprocess_nodes(nodes, query_bundle=query)

        # Pass-through 模式：直接截断返回前 top_n
        return nodes[: self._top_n]

    async def arerank(
        self,
        query: str | QueryBundle,
        nodes: list[NodeWithScore],
    ) -> list[NodeWithScore]:
        """异步版本（委托同步方法）。"""
        return self.rerank(query, nodes)
