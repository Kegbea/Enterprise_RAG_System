"""评估执行器 — 串联 ETL 入库 → 检索 → 生成 → Ragas 评分。

Usage:
    from app.eval.runner import EvalRunner
    from app.eval.dataset import load_qa_dataset

    runner = EvalRunner(persist_dir="data/eval_store")
    runner.ingest_eval_docs(["data/eval/sample_knowledge.md"])
    report = await runner.run_evaluation(load_qa_dataset("data/eval/qa_pairs.json"))
    print(report.to_console())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from ragas import EvaluationDataset, SingleTurnSample, evaluate

from app.config import settings
from app.etl.pipeline import ETLPipeline, InMemoryDocStore
from app.eval.dataset import QASample
from app.eval.metrics import get_evaluator_embeddings, get_ragas_metrics
from app.eval.report import EvalReport
from app.services.query_service import QueryService

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """单次查询的完整结果（检索 + 生成）。"""

    user_input: str
    response: str = ""
    retrieved_contexts: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""


class EvalRunner:
    """RAG 评估执行器 — 管理文档入库和评估流程。

    复用的现有组件：
    - InMemoryDocStore: 文档存储（评估使用独立持久化目录）
    - ETLPipeline: 文档解析 → 清洗 → 切块 → 入库
    - QueryService: RAG 引擎管理（延迟初始化 + 检索 + 生成）
    """

    def __init__(self, persist_dir: str | None = None) -> None:
        """初始化评估执行器。

        Args:
            persist_dir: 评估专用的持久化目录（默认使用独立目录，不与生产数据混合）
        """
        self._persist_dir = persist_dir or str(
            Path(settings.storage_dir) / "eval"
        )
        self._store = InMemoryDocStore(persist_dir=self._persist_dir)
        self._pipeline = ETLPipeline(store=self._store)
        self._query_service: QueryService | None = None

    # ── 文档入库 ───────────────────────────────────────────

    def ingest_eval_docs(self, doc_paths: list[str | Path]) -> list[str]:
        """将评估用文档通过 ETL 管道入库并构建索引。

        Args:
            doc_paths: 文档文件路径列表

        Returns:
            成功入库的文件路径列表
        """
        ingested: list[str] = []
        for p in doc_paths:
            path = Path(p)
            if not path.exists():
                logger.warning(f"评估文档不存在，跳过: {path}")
                continue
            try:
                result = self._pipeline.ingest_bytes(
                    file_bytes=path.read_bytes(),
                    filename=path.name,
                    overwrite=False,
                )
                if result.status in ("created", "overwritten"):
                    ingested.append(path.name)
                    logger.info(
                        f"已入库: {path.name} ({result.chunks_created} chunks)"
                    )
                elif result.status == "skipped":
                    ingested.append(path.name)
                    logger.info(f"已存在: {path.name}（跳过）")
                else:
                    logger.warning(
                        f"入库失败: {path.name} — {result.error_message}"
                    )
            except Exception as e:
                logger.error(f"入库异常: {path.name} — {e}")

        # 入库后初始化/刷新引擎
        self._ensure_engine()
        return ingested

    # ── 查询执行 ───────────────────────────────────────────

    async def run_query(self, query: str) -> QueryResult:
        """对已索引文档执行单次查询，返回检索结果和生成回答。

        同时记录检索到的上下文（retrieved_contexts）和 LLM 回答（response），
        供 Ragas 评估使用。

        Args:
            query: 用户问题

        Returns:
            QueryResult 包含回答、检索上下文、延迟、错误信息
        """
        start = time.perf_counter()
        result = QueryResult(user_input=query)

        if not self._ensure_engine():
            result.error = "RAG engine not ready"
            result.latency_ms = (time.perf_counter() - start) * 1000
            return result

        try:
            qs = self._query_service

            # 1. 检索 — 获取上下文片段
            nodes = qs._retriever.retrieve(query)
            result.retrieved_contexts = [
                n.text for n in nodes if n.text
            ]

            # 2. 生成 — 非流式获取完整回答
            query_result = await qs._engine.query(query)
            result.response = query_result.answer

        except Exception as e:
            logger.error(f"查询失败: {query} — {e}")
            result.error = str(e)

        result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    # ── 评估执行 ───────────────────────────────────────────

    async def run_evaluation(
        self,
        samples: list[QASample],
        metrics: list | None = None,
    ) -> EvalReport:
        """执行完整 RAG 评估流程。

        对每个 QASample：
        1. 调用 run_query() 获取检索上下文和生成回答
        2. 填充 response 和 retrieved_contexts
        3. 构造 Ragas SingleTurnSample
        4. 批量调用 ragas.evaluate() 计算指标

        Args:
            samples: 评估样本列表（已含 user_input, reference, reference_contexts）
            metrics: Ragas 指标列表（None 则使用默认五指标）

        Returns:
            EvalReport 包含汇总指标和逐条详情
        """
        if metrics is None:
            metrics = get_ragas_metrics()

        ragas_samples: list[SingleTurnSample] = []
        query_results: list[QueryResult] = []
        total_latency_ms = 0.0

        logger.info(f"开始评估 {len(samples)} 条样本...")

        for i, sample in enumerate(samples):
            logger.info(f"  [{i + 1}/{len(samples)}] 查询: {sample.user_input[:60]}...")

            qr = await self.run_query(sample.user_input)
            query_results.append(qr)
            total_latency_ms += qr.latency_ms

            sample.response = qr.response
            sample.retrieved_contexts = qr.retrieved_contexts

            ragas_samples.append(
                SingleTurnSample(
                    user_input=sample.user_input,
                    response=qr.response if qr.response else "(no response)",
                    retrieved_contexts=qr.retrieved_contexts or ["(no contexts)"],
                    reference=sample.reference,
                    reference_contexts=sample.reference_contexts,
                )
            )

        # 批量评估
        dataset = EvaluationDataset(ragas_samples)
        embeddings = get_evaluator_embeddings()
        logger.info(f"计算 Ragas 指标（{len(metrics)} 个）...")

        scores = evaluate(
            dataset=dataset,
            metrics=metrics,
            embeddings=embeddings,
            show_progress=True,
        )

        # 解析分数
        metric_values = self._parse_scores(scores)
        avg_latency = total_latency_ms / len(samples) if samples else 0

        # 逐条详情
        individual_scores: list[dict] = []
        for i, sample in enumerate(samples):
            resp = sample.response
            ref = sample.reference
            individual_scores.append({
                "user_input": sample.user_input,
                "response": resp[:200] + "..." if len(resp) > 200 else resp,
                "reference": ref[:200] + "..." if len(ref) > 200 else ref,
                "retrieved_count": len(sample.retrieved_contexts),
                "error": query_results[i].error if i < len(query_results) else "",
            })

        logger.info(
            f"评估完成: {len(samples)} 条样本, "
            f"平均延迟 {avg_latency:.0f}ms, "
            f"{len(metric_values)} 项指标"
        )

        return EvalReport(
            metrics=metric_values,
            individual_scores=individual_scores,
            total_queries=len(samples),
            avg_latency_ms=avg_latency,
        )

    # ── 内部方法 ───────────────────────────────────────────

    def _ensure_engine(self) -> bool:
        """确保 QueryService 已初始化并有可用引擎。"""
        if self._query_service is None:
            self._query_service = QueryService(self._store)
        return self._query_service.ensure_ready()

    @staticmethod
    def _parse_scores(scores) -> dict[str, float]:
        """解析 ragas.evaluate() 返回的分数对象。

        ragas 返回 EvaluationResult 对象，可通过 to_pandas() 转 DataFrame。
        此处提取各指标的平均值。
        """
        try:
            df = scores.to_pandas()
            result: dict[str, float] = {}
            for col in df.columns:
                if col not in ("user_input", "retrieved_contexts", "response",
                               "reference", "reference_contexts"):
                    try:
                        vals = df[col].dropna()
                        if len(vals) > 0:
                            result[col] = float(vals.mean())
                    except (TypeError, ValueError):
                        pass
            return result
        except Exception as e:
            logger.warning(f"Failed to parse evaluation scores: {e}")
            # 回退：尝试直接提取
            try:
                return {str(k): float(v) for k, v in scores.items()}
            except Exception:
                return {"error": str(e)}
