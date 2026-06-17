"""评估数据集加载与验证。

数据集格式（JSON）:
    [
      {
        "user_input": "什么是混合检索？",
        "reference": "混合检索结合了 BM25 和稠密检索...",
        "reference_contexts": ["BM25 基于关键词...", "Dense 检索基于语义..."],
        "source_document": "sample_knowledge.md"
      }
    ]

Usage:
    from app.eval.dataset import load_qa_dataset, EvalSample, QASample
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 数据类 ──────────────────────────────────────────────────


@dataclass
class QASample:
    """单条评估样本。

    Attributes:
        user_input: 用户问题
        reference: 参考答案（ground truth answer）
        reference_contexts: 参考上下文片段列表（ground truth contexts）
        source_document: 关联的知识文档文件名（可选）
    """

    user_input: str
    reference: str
    reference_contexts: list[str] = field(default_factory=list)
    source_document: str = ""

    # 以下字段由 EvalRunner 填充
    response: str = ""
    retrieved_contexts: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> QASample:
        """从字典构造，验证必填字段。"""
        if not data.get("user_input", "").strip():
            raise ValueError("QASample must have non-empty 'user_input'")
        if not data.get("reference", "").strip():
            raise ValueError("QASample must have non-empty 'reference'")
        return cls(
            user_input=data["user_input"].strip(),
            reference=data["reference"].strip(),
            reference_contexts=data.get("reference_contexts", []),
            source_document=data.get("source_document", ""),
        )


# ── 加载函数 ────────────────────────────────────────────────


def load_qa_dataset(path: str | Path) -> list[QASample]:
    """从 JSON 文件加载评估数据集。

    Args:
        path: JSON 文件路径（QASample 对象数组）

    Returns:
        QASample 列表

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 格式错误或字段缺失
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"评估数据集文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析错误: {e}") from e

    if not isinstance(raw, list):
        raise ValueError("评估数据集必须是 JSON 数组")

    samples = []
    for i, item in enumerate(raw):
        try:
            samples.append(QASample.from_dict(item))
        except ValueError as e:
            raise ValueError(f"第 {i} 条样本无效: {e}") from e

    logger.info("加载 %d 条评估样本 (from %s)", len(samples), path.name)
    return samples


def load_knowledge_document(path: str | Path) -> bytes:
    """读取评估用知识文档的原始字节。

    Args:
        path: 文档文件路径

    Returns:
        文件内容（bytes）

    Raises:
        FileNotFoundError: 文件不存在
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"评估文档不存在: {path}")
    return path.read_bytes()
