"""RAG 评估模块 — Ragas 指标 + 数据集管理 + 评估执行。

兼容性说明：
    ragas==0.4.3 无条件导入 langchain_community.chat_models.vertexai.ChatVertexAI，
    但 langchain-community>=0.4.0 已移除该模块（迁移到 langchain-google-vertexai）。
    此处自动在 langchain_community/chat_models/ 下创建 vertexai.py 桥接文件。

Usage:
    from app.eval.runner import EvalRunner
    from app.eval.dataset import load_qa_dataset
"""

from __future__ import annotations

import os

# ── Ragas 兼容性补丁 ────────────────────────────────────────

def _patch_vertexai_import() -> None:
    """在 langchain_community/chat_models/ 下创建 vertexai.py 桥接文件。

    ragas.llms.base 执行:
        from langchain_community.chat_models.vertexai import ChatVertexAI
        from langchain_community.llms import VertexAI

    llms/vertexai.py 仍存在于 langchain-community==0.4.2 中，
    但 chat_models/vertexai.py 已被移除。此处创建桥接文件重新导出。
    """
    import langchain_community as _lc

    _pkg_dir = os.path.dirname(os.path.abspath(_lc.__file__))
    _target = os.path.join(_pkg_dir, "chat_models", "vertexai.py")

    # 幂等：文件已存在则跳过
    if os.path.exists(_target):
        return

    _content = '''"""Ragas 兼容性桥接 — 从 langchain_google_vertexai 重新导出 ChatVertexAI。"""
from langchain_google_vertexai.chat_models import ChatVertexAI  # noqa: F401
'''

    try:
        with open(_target, "w", encoding="utf-8") as f:
            f.write(_content)
    except OSError:
        # 无写权限时静默失败，后续 ragas 导入会给出清晰的 ImportError
        pass


_patch_vertexai_import()
