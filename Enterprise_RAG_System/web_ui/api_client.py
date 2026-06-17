"""Streamlit 前端 → 后端 API 客户端。

封装所有 HTTP 调用，统一错误处理。
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


class APIClient:
    """后端 API 客户端。

    Usage:
        client = APIClient("http://localhost:8000")
        result = client.upload_document(file, ...)
        for event in client.stream_chat("问题"):
            ...
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self._api_key = os.getenv("API_KEY", "")

    def _headers(self) -> dict[str, str]:
        """构造通用请求头，包含 API Key（如有配置）。"""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    # ── 文档管理 ────────────────────────────────────────

    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        department_id: str = "public",
        tags: list[str] | None = None,
        custom_metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """上传文档触发 ETL 入库。"""
        files = {"file": (filename, file_bytes)}
        data = {
            "department_id": department_id,
            "tags": ",".join(tags) if tags else "",
            "custom_metadata": json.dumps(custom_metadata or {}),
            "overwrite": str(overwrite).lower(),
        }
        resp = requests.post(
            f"{self.base_url}/api/documents/upload",
            files=files,
            data=data,
            timeout=120,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def check_document_status(self, checksum: str) -> dict[str, Any]:
        """通过 checksum 检查文档是否已入库。"""
        resp = requests.get(
            f"{self.base_url}/api/documents/status/{checksum}", timeout=10,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    # ── 对话 ────────────────────────────────────────────

    def stream_chat(
        self,
        query: str,
        chat_history: list[dict[str, str]] | None = None,
    ):
        """流式对话生成器，逐条产出 SSE 事件 (event_type, data_dict)。"""
        body: dict[str, Any] = {"query": query}
        if chat_history:
            body["chat_history"] = chat_history

        resp = requests.post(
            f"{self.base_url}/api/chat/stream",
            json=body,
            stream=True,
            timeout=120,
            headers=self._headers(),
        )
        resp.raise_for_status()

        # 解析 SSE 事件流（先 normalize 行尾，兼容 \r\n）
        buffer = ""
        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
            if chunk is None:
                continue
            buffer += chunk.replace("\r\n", "\n")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                event_type, data = _parse_sse_block(block)
                if event_type and data is not None:
                    yield event_type, data

    def health_check(self) -> dict[str, Any]:
        """健康检查。"""
        resp = requests.get(f"{self.base_url}/health", timeout=5,
            headers=self._headers())
        resp.raise_for_status()
        return resp.json()


def _parse_sse_block(block: str) -> tuple[str | None, dict | None]:
    """解析单个 SSE 事件块，返回 (event_type, data_dict)。"""
    event_type = None
    data_str = None
    for line in block.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]
    if data_str is None:
        return None, None
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        return None, None
    return event_type, data
