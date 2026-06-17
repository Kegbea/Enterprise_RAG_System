"""流式查询引擎 — 检索 → 重排序 → LLM 生成 → SSE 流式输出。

协议：Server-Sent Events (text/event-stream)
事件类型：
- token:    流式文本增量  {"token": "..."}
- citation: 引用来源声明  {"sources": [{...}, ...]}
- done:     结束信号      {"status": "complete", "token_count": N}

内部设计：
    _query_events() → AsyncGenerator[(event_type, payload), None]
        ↑ 结构化事件流（内部使用、测试友好）
    query_stream() → AsyncGenerator[str, None]
        ↑ SSE 格式化（前端消费）
    query() → QueryResult
        ↑ 非流式汇总（调试/测试使用）

引用追踪设计：
    检索结果的 node.metadata 携带 filename、page_number、heading_path、
    chunk_type、department_id 等字段。前端引用卡片和 SSE citation 事件
    均从 metadata 提取——**不由 LLM 生成**，避免幻觉引用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.core.schema import NodeWithScore
from llama_index.llms.dashscope import DashScope

from app.config import settings

logger = logging.getLogger(__name__)

# ── 系统提示词 ──────────────────────────────────────────

SYSTEM_PROMPT = """你是一个企业级知识问答助手。请严格基于提供的文档片段回答问题。

规则：
1. 回答时引用具体文档来源（文件名 + 页码 + 标题路径）
2. 如果文档片段不足以回答问题，明确告知用户，不要编造
3. 回答简洁专业，使用中文
4. 表格数据以 Markdown 表格格式呈现
"""


# ── 数据类 ──────────────────────────────────────────────


@dataclass
class CitationSource:
    """单个引用来源。"""
    filename: str
    page_number: int | None = None
    heading_path: str = ""
    chunk_type: str = "text"
    snippet: str = ""  # 前 200 字摘要
    node_id: str = ""


@dataclass
class QueryResult:
    """查询结果汇总（非流式场景使用）。"""
    answer: str = ""
    citations: list[CitationSource] = field(default_factory=list)
    token_count: int = 0


# ── SSE 事件构造 ────────────────────────────────────────


def _sse_event(event: str, data: dict | str) -> str:
    """构造 SSE 格式事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data
    return f"event: {event}\ndata: {payload}\n\n"


# ── 查询引擎 ────────────────────────────────────────────


class QueryEngine:
    """流式查询引擎 — 全链路：检索 → 重排序 → LLM → SSE。

    Usage:
        engine = QueryEngine(hybrid_retriever, reranker)
        async for event in engine.query_stream("什么是混合检索？"):
            yield event  # SSE 格式字符串
    """

    def __init__(
        self,
        hybrid_retriever,   # HybridRetriever（避免循环导入）
        reranker,            # Reranker
        llm_model: str | None = None,
        system_prompt: str | None = None,
    ):
        self._retriever = hybrid_retriever
        self._reranker = reranker
        self._llm = DashScope(
            model_name=llm_model or settings.llm_model,
            api_key=settings.dashscope_api_key,
            temperature=settings.llm_temperature,
        )
        self._system_prompt = system_prompt or SYSTEM_PROMPT

    # ── 公开接口 ────────────────────────────────────────

    async def query_stream(
        self,
        query: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """执行查询并以 SSE 事件流返回。

        Args:
            query: 用户问题
            chat_history: 可选对话历史 [{"role": "user", "content": "..."}, ...]

        Yields:
            SSE 格式事件字符串（token / citation / done）
        """
        async for event_type, payload in self._query_events(query, chat_history):
            yield _sse_event(event_type, payload)

    async def query(self, query: str) -> QueryResult:
        """非流式查询，返回完整结果。调试/测试场景使用。

        直接消费内部结构化事件流，不再二次解析 SSE 字符串。
        """
        answer_parts: list[str] = []
        citations: list[CitationSource] = []

        async for event_type, payload in self._query_events(query):
            if event_type == "token":
                answer_parts.append(payload["token"])
            elif event_type == "citation":
                citations = [
                    CitationSource(**s) for s in payload.get("sources", [])
                ]

        return QueryResult(
            answer="".join(answer_parts),
            citations=citations,
            token_count=len(answer_parts),
        )

    # ── 内部事件流 ──────────────────────────────────────

    async def _query_events(
        self,
        query: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """结构化查询事件流 — 内部使用，不耦合 SSE 格式。

        Yields:
            (event_type, payload) 元组。event_type ∈ {"citation", "token", "done"}
        """
        # 1. 检索
        nodes = self._retriever.retrieve(query)
        if not nodes:
            yield ("done", {"status": "no_results", "token_count": 0})
            return

        # 2. 重排序
        reranked = self._reranker.rerank(query, nodes)

        # 3. 构造 citations
        citations = _extract_citations(reranked)
        yield ("citation", {
            "sources": [c.__dict__ for c in citations],
        })

        # 4. 构造 LLM 消息
        context = _build_context(reranked)
        messages = _build_messages(
            system_prompt=self._system_prompt,
            context=context,
            query=query,
            chat_history=chat_history,
        )

        # 5. 流式生成
        token_count = 0
        stream = await self._llm.astream_chat(messages)
        async for chunk in stream:
            delta = chunk.delta or ""
            if delta:
                token_count += 1
                yield ("token", {"token": delta})

        # 6. 结束信号
        yield ("done", {"status": "complete", "token_count": token_count})


# ── 辅助函数 ────────────────────────────────────────────


def _extract_citations(nodes: list[NodeWithScore]) -> list[CitationSource]:
    """从检索结果的 metadata 提取引用来源。"""
    citations: list[CitationSource] = []
    seen = set()
    for node in nodes:
        meta = node.metadata
        key = (meta.get("filename", ""), meta.get("page_number", -1))
        if key in seen:
            continue
        seen.add(key)
        snippet = node.text[:200].replace("\n", " ") if node.text else ""
        citations.append(CitationSource(
            filename=meta.get("filename", "unknown"),
            page_number=meta.get("page_number"),
            heading_path=meta.get("heading_path", ""),
            chunk_type=meta.get("chunk_type", "text"),
            snippet=snippet,
            node_id=node.node_id,
        ))
    return citations


def _build_context(nodes: list[NodeWithScore]) -> str:
    """将检索节点拼接为 LLM 上下文。"""
    parts: list[str] = []
    for i, node in enumerate(nodes, 1):
        meta = node.metadata
        source = meta.get("filename", "unknown")
        page = f" 第{meta.get('page_number')}页" if meta.get("page_number") else ""
        heading = f" > {meta['heading_path']}" if meta.get("heading_path") else ""
        header = f"[来源 {i}：{source}{page}{heading}]"
        parts.append(f"{header}\n{node.text}")
    return "\n\n---\n\n".join(parts)


def _build_messages(
    system_prompt: str,
    context: str,
    query: str,
    chat_history: list[dict[str, str]] | None = None,
) -> list[ChatMessage]:
    """构造 LLM 对话消息列表。"""
    messages: list[ChatMessage] = []

    # System
    full_system = f"{system_prompt}\n\n以下是相关文档片段：\n\n{context}"
    messages.append(ChatMessage(role=MessageRole.SYSTEM, content=full_system))

    # History
    if chat_history:
        for msg in chat_history:
            role = MessageRole.USER if msg["role"] == "user" else MessageRole.ASSISTANT
            messages.append(ChatMessage(role=role, content=msg["content"]))

    # Current query
    messages.append(ChatMessage(role=MessageRole.USER, content=query))

    return messages
