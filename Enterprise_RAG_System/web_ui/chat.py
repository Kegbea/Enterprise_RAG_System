"""聊天页面 — 流式对话、引用卡片、对话历史管理。

SSE 事件流处理：
- citation → 渲染引用卡片（文件名、页码、标题路径、摘要）
- token → 累积到当前回答并实时刷新
- done → 标记回答完成
"""

from __future__ import annotations


def render(api_base_url: str) -> None:
    """渲染聊天页面。

    Args:
        api_base_url: 后端 API 地址，如 http://localhost:8000
    """
    import streamlit as st

    from web_ui.api_client import APIClient

    # ── 初始化 ──────────────────────────────────────────

    # 页面级 CSS：引用卡片样式
    _inject_css()

    client = APIClient(api_base_url)

    # 对话历史：session_state 持久化
    if "messages" not in st.session_state:
        st.session_state.messages = []  # [{"role": "user", "content": "..."}, ...]
    if "citations_store" not in st.session_state:
        st.session_state.citations_store = {}  # {answer_index: [citation_dict, ...]}

    # ── 工具栏 ──────────────────────────────────────────

    col_toolbar = st.columns([3, 1])
    with col_toolbar[1]:
        if st.button("🗑️ 清空对话", use_container_width=True):
            st.session_state.messages = []
            st.session_state.citations_store = {}
            st.rerun()

    # ── 渲染历史消息 ────────────────────────────────────

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # 渲染该回答对应的引用
            if msg["role"] == "assistant" and i in st.session_state.citations_store:
                _render_citations(st.session_state.citations_store[i])

    # ── 输入框 ──────────────────────────────────────────

    if prompt := st.chat_input("输入你的问题，Enter 发送..."):
        # 追加用户消息
        st.session_state.messages.append({"role": "user", "content": prompt})

        # 构造历史（不含当前问题）
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
        ]

        # 流式累积回答
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            current_text: str = ""
            citations: list[dict] = []

            try:
                for event_type, data in client.stream_chat(prompt, history):
                    if event_type == "citation":
                        citations = data.get("sources", [])
                    elif event_type == "token":
                        current_text += data.get("token", "")
                        placeholder.markdown(current_text + "▌")
                    elif event_type == "done":
                        if not current_text:
                            current_text = "未找到相关文档信息，请尝试其他问题。"
                        placeholder.markdown(current_text)
                        if citations:
                            _render_citations(citations)
            except Exception as exc:
                placeholder.error(f"请求失败：{exc}")
                current_text = f"*[错误] {exc}*"

            # 保存回答到历史
            answer_text = current_text or "*[无响应]*"
            st.session_state.messages.append({"role": "assistant", "content": answer_text})
            answer_idx = len(st.session_state.messages) - 1
            if citations:
                st.session_state.citations_store[answer_idx] = citations


# ── UI 辅助 ──────────────────────────────────────────────


def _inject_css() -> None:
    """注入自定义 CSS 样式。"""
    import streamlit as st

    st.markdown("""
    <style>
    .citation-card {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 8px 12px;
        margin: 4px 0;
        font-size: 0.85em;
        background: #fafafa;
    }
    .citation-card .meta {
        font-weight: 600;
        color: #333;
    }
    .citation-card .snippet {
        color: #666;
        margin-top: 4px;
        font-style: italic;
    }
    /* Streamlit chat message 内部间距调整 */
    .stChatMessage {
        padding-bottom: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)


def _render_citations(citations: list[dict]) -> None:
    """渲染引用来源卡片列表。"""
    import streamlit as st

    if not citations:
        return

    st.markdown("**📚 引用来源：**")
    for c in citations:
        filename = c.get("filename", "unknown")
        page = f" 第{c['page_number']}页" if c.get("page_number") else ""
        heading = f" > {c['heading_path']}" if c.get("heading_path") else ""
        snippet = c.get("snippet", "")[:200]

        st.markdown(f"""
        <div class="citation-card">
            <div class="meta">📄 {filename}{page} &nbsp; {heading}</div>
            <div class="snippet">{snippet}</div>
        </div>
        """.replace(">", "&gt;").replace("<", "&lt;"), unsafe_allow_html=True)
