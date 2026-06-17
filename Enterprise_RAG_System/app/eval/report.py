"""评估报告生成 — 控制台输出和 JSON 序列化。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EvalReport:
    """RAG 评估报告。

    Attributes:
        metrics: 指标名称 → 平均分值
        individual_scores: 逐条详情列表
        total_queries: 评估查询总数
        avg_latency_ms: 平均查询延迟（毫秒）
        timestamp: 报告生成时间（UTC）
    """

    metrics: dict[str, float] = field(default_factory=dict)
    individual_scores: list[dict] = field(default_factory=list)
    total_queries: int = 0
    avg_latency_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_console(self) -> str:
        """格式化为控制台输出字符串。"""
        lines = [
            "=" * 64,
            "  RAG 评估报告",
            "=" * 64,
            f"  评估样本数: {self.total_queries}",
            f"  平均延迟:   {self.avg_latency_ms:.0f}ms",
            f"  报告时间:   {self.timestamp}",
            "",
            "  ── 指标汇总 ──",
        ]

        if not self.metrics:
            lines.append("  (无指标数据)")

        # 指标标签中文映射
        labels: dict[str, str] = {
            "context_precision": "上下文精确率",
            "context_recall": "上下文召回率",
            "faithfulness": "忠实度",
            "answer_relevancy": "回答相关性",
            "answer_correctness": "回答正确性",
        }

        for key, value in self.metrics.items():
            label = labels.get(key, key)
            bar = _score_bar(value)
            lines.append(f"  {label:<14s}: {value:>6.4f}  {bar}")

        lines.append("")
        lines.append("  ── 逐条结果 ──")

        for i, item in enumerate(self.individual_scores, 1):
            lines.append(f"  [{i}] Q: {item.get('user_input', '?')[:80]}")
            lines.append(f"      A: {item.get('response', '(空)')[:120]}")
            error = item.get("error", "")
            if error:
                lines.append(f"      ⚠ 错误: {error}")

        lines.append("")
        lines.append("=" * 64)
        return "\n".join(lines)

    def to_json(self, path: str | Path | None = None) -> str:
        """序列化为 JSON 字符串或写入文件。

        Args:
            path: 可选输出路径（写入文件），None 则返回字符串

        Returns:
            JSON 字符串
        """
        data = {
            "timestamp": self.timestamp,
            "total_queries": self.total_queries,
            "avg_latency_ms": self.avg_latency_ms,
            "metrics": self.metrics,
            "individual_scores": self.individual_scores,
        }
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        if path:
            Path(path).write_text(json_str, encoding="utf-8")
            logger.info(f"报告已保存: {path}")
        return json_str


def _score_bar(value: float, width: int = 20) -> str:
    """生成可视化分数条（ASCII 字符，兼容所有终端）。"""
    filled = int(round(value * width))
    filled = min(filled, width)
    return "#" * filled + "-" * (width - filled)
