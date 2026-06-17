"""RAG 评估指标配置 — 使用 Ragas 评估检索和生成质量。

指标说明：
    - context_precision: 检索到的上下文中，有多少与参考答案相关
    - context_recall: 参考答案中，有多少能从检索上下文中找到
    - faithfulness: 生成的回答是否完全基于检索上下文（无幻觉）
    - answer_relevancy: 生成的回答与问题的相关程度
    - answer_correctness: 生成的回答与参考答案的一致性

Usage:
    from app.eval.metrics import get_ragas_metrics
    metrics = get_ragas_metrics()
"""

from __future__ import annotations

import logging

from openai import OpenAI
from ragas.llms import llm_factory

from app.config import settings

logger = logging.getLogger(__name__)

# DashScope OpenAI 兼容端点
_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# 缓存，避免重复创建
_evaluator_llm = None
_evaluator_embeddings = None


def _create_evaluator_llm():
    """创建 Ragas 评估器 LLM（DashScope OpenAI 兼容端点）。

    返回 Ragas 的 InstructorBaseRagasLLM 实例，可直接赋值给 Metric.llm。
    """
    client = OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=_DASHSCOPE_BASE_URL,
    )
    return llm_factory(
        model=settings.llm_model,  # "qwen-plus"
        client=client,
    )


def get_evaluator_llm():
    """获取全局缓存的评估器 LLM 实例（单例）。"""
    global _evaluator_llm
    if _evaluator_llm is None:
        _evaluator_llm = _create_evaluator_llm()
        logger.info(f"Evaluator LLM initialized: {settings.llm_model}")
    return _evaluator_llm


def get_ragas_metrics():
    """返回完整的 RAG 评估指标列表。

    包括：
        - context_precision（上下文精确率）
        - context_recall（上下文召回率）
        - faithfulness（忠实度）
        - answer_relevancy（回答相关性）
        - answer_correctness（回答正确性）

    Returns:
        list[Metric]: Ragas 指标对象列表，每个已注入评估 LLM
    """
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )
    from ragas.metrics._answer_correctness import AnswerCorrectness

    llm = get_evaluator_llm()

    metrics = [
        context_precision,
        context_recall,
        faithfulness,
        answer_relevancy,
    ]
    for m in metrics:
        m.llm = llm

    answer_correctness = AnswerCorrectness(llm=llm)
    metrics.append(answer_correctness)

    return metrics


def get_evaluator_embeddings():
    """获取全局缓存的评估器 Embedding 实例（单例）。

    使用 DashScope OpenAI 兼容端点，通过 LangChain OpenAIEmbeddings +
    Ragas LangchainEmbeddingsWrapper 桥接。

    Returns:
        LangchainEmbeddingsWrapper: Ragas 兼容的 embedding 实例
    """
    global _evaluator_embeddings
    if _evaluator_embeddings is None:

        from langchain_openai import OpenAIEmbeddings
        from ragas.embeddings.base import LangchainEmbeddingsWrapper

        _evaluator_embeddings = LangchainEmbeddingsWrapper(
            OpenAIEmbeddings(
                model=settings.embedding_model,
                api_key=settings.dashscope_api_key,
                base_url=_DASHSCOPE_BASE_URL,
                check_embedding_ctx_length=False,
            )
        )
        logger.info(f"Evaluator embeddings initialized: {settings.embedding_model}")
    return _evaluator_embeddings
