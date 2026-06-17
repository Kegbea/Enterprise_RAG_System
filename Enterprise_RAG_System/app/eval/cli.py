"""评估命令行入口。

Usage:
    uv run python -m app.eval.cli                          # 使用默认数据集
    uv run python -m app.eval.cli --dataset path/to/qa.json  # 指定数据集
    uv run python -m app.eval.cli --mock                     # Mock 模式（不调用 API）
    uv run python -m app.eval.cli --output report.json       # 保存 JSON 报告
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

# 在导入其他模块前先应用 ragas 兼容补丁
import app.eval  # noqa: F401  — 触发 _patch_vertexai_import()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG 评估工具 — 使用 Ragas 指标评估检索和生成质量",
    )
    parser.add_argument(
        "--dataset",
        default="data/eval/qa_pairs.json",
        help="评估数据集 JSON 文件路径（默认: data/eval/qa_pairs.json）",
    )
    parser.add_argument(
        "--doc-dir",
        default="data/eval",
        help="评估文档目录（默认: data/eval）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="JSON 报告输出路径（默认: 仅控制台输出）",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Mock 模式：不调用 LLM API，使用占位回答",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出",
    )
    args = parser.parse_args()

    # 日志
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-5s %(name)s — %(message)s",
    )

    if args.mock:
        _run_mock(args)
    else:
        asyncio.run(_run_real(args))


async def _run_real(args) -> None:
    """真实评估模式 — 调用 LLM API。"""
    from app.eval.dataset import load_qa_dataset
    from app.eval.metrics import get_ragas_metrics
    from app.eval.runner import EvalRunner

    # 1. 加载数据集
    print(f"加载数据集: {args.dataset}")
    samples = load_qa_dataset(args.dataset)

    # 2. 搜索评估文档
    doc_dir = Path(args.doc_dir)
    docs = sorted(doc_dir.rglob("*.md")) + sorted(doc_dir.rglob("*.txt"))
    docs += sorted(doc_dir.rglob("*.pdf")) + sorted(doc_dir.rglob("*.docx"))
    docs = list(dict.fromkeys(docs))  # 去重保序

    # 3. 入库并初始化引擎
    runner = EvalRunner()
    if docs:
        print(f"入库 {len(docs)} 个评估文档...")
        runner.ingest_eval_docs([str(d) for d in docs])
    else:
        print(f"警告: {doc_dir} 中未找到评估文档，请确保已有文档入库")

    # 4. 运行评估
    print(f"开始评估 {len(samples)} 条查询...")
    metrics = get_ragas_metrics()
    report = await runner.run_evaluation(samples, metrics=metrics)

    # 5. 输出报告
    print()
    print(report.to_console())

    if args.output:
        report.to_json(args.output)
        print(f"\nJSON 报告已保存: {args.output}")


def _run_mock(args) -> None:
    """Mock 模式 — 使用占位数据验证评估流程，不调用 API。"""
    from app.config import settings
    from app.eval.dataset import QASample
    from app.eval.metrics import get_ragas_metrics
    from app.eval.report import EvalReport

    print("Mock 模式 — 使用占位数据验证评估流程\n")

    # 构造 mock 样本（模拟已有检索和生成结果）
    mock_samples = [
        QASample(
            user_input="什么是RAG？",
            reference="RAG是检索增强生成技术。",
            reference_contexts=["RAG结合了检索和生成。"],
            response="RAG（检索增强生成）是一种AI技术。",
            retrieved_contexts=[
                "RAG（Retrieval-Augmented Generation）是一种结合检索与生成的AI技术。"
            ],
        ),
        QASample(
            user_input="BM25是什么？",
            reference="BM25是一种基于词频的检索算法。",
            reference_contexts=["BM25基于词频统计。"],
            response="BM25是经典的关键词检索算法。",
            retrieved_contexts=["BM25（Best Match 25）是基于词频统计的经典检索算法。"],
        ),
    ]

    from ragas import EvaluationDataset, SingleTurnSample, evaluate

    ragas_samples = [
        SingleTurnSample(
            user_input=s.user_input,
            response=s.response,
            retrieved_contexts=s.retrieved_contexts,
            reference=s.reference,
            reference_contexts=s.reference_contexts,
        )
        for s in mock_samples
    ]

    from app.eval.runner import EvalRunner

    metrics = get_ragas_metrics()
    dataset = EvaluationDataset(ragas_samples)

    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings.base import LangchainEmbeddingsWrapper

    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            model="text-embedding-v3",
            api_key=settings.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            check_embedding_ctx_length=False,
        )
    )

    print(f"计算 {len(metrics)} 个指标...")
    scores = evaluate(
        dataset=dataset,
        metrics=metrics,
        embeddings=embeddings,
        show_progress=True,
    )

    metric_values = EvalRunner._parse_scores(scores)

    report = EvalReport(
        metrics=metric_values,
        individual_scores=[
            {
                "user_input": s.user_input,
                "response": s.response,
                "reference": s.reference,
            }
            for s in mock_samples
        ],
        total_queries=len(mock_samples),
        avg_latency_ms=0,
    )

    print()
    print(report.to_console())

    if args.output:
        report.to_json(args.output)
        print(f"\nJSON 报告已保存: {args.output}")


if __name__ == "__main__":
    main()
