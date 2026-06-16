"""Enterprise RAG System — Streamlit 前端入口。

启动方式：
    uv run streamlit run web_ui/app.py

功能页面：
- 💬 智能问答：流式对话 + 引用追踪
- 📁 文档管理：上传文档 + 查看入库状态
"""

from __future__ import annotations

import streamlit as st

# ── 页面配置（必须是第一个 st 命令） ───────────────────

st.set_page_config(
    page_title="Enterprise RAG System",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 侧边栏 — 导航 + 后端连接配置 ──────────────────────

st.sidebar.title("🔍 Enterprise RAG")
st.sidebar.caption("企业级智能知识问答系统")

# 后端地址配置
api_base_url = st.sidebar.text_input(
    "后端 API 地址",
    value="http://localhost:8000",
    help="FastAPI 后端地址，默认 http://localhost:8000",
)

# 健康状态指示器
if st.sidebar.button("🔗 检查连接"):
    from web_ui.api_client import APIClient

    client = APIClient(api_base_url)
    try:
        health = client.health_check()
        st.sidebar.success(f"✅ 已连接 · 模型：{health.get('llm_model', 'N/A')}")
    except Exception as exc:
        st.sidebar.error(f"❌ 连接失败：{exc}")

st.sidebar.divider()

# 页面导航
page = st.sidebar.radio(
    "导航",
    options=["💬 智能问答", "📁 文档管理"],
    help="切换功能页面",
)

st.sidebar.divider()
st.sidebar.caption("v0.1.0 · FastAPI + Streamlit + ChromaDB")

# ── 页面路由 ──────────────────────────────────────────

if page == "💬 智能问答":
    from web_ui.chat import render as chat_render

    chat_render(api_base_url)
elif page == "📁 文档管理":
    from web_ui.documents import render as docs_render

    docs_render(api_base_url)
