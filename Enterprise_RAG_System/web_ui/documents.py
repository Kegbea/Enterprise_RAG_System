"""文档管理页面 — 上传文档、查看入库状态。

功能：
- 拖拽/点击上传文档（PDF/DOCX/MD/TXT）
- 预览文件名、大小、类型
- 显示入库结果（文档数、chunk 数、checksum）
- 查看文档入库状态
"""

from __future__ import annotations

import streamlit as st

from web_ui.api_client import APIClient


def render(api_base_url: str) -> None:
    """渲染文档管理页面。"""
    client = APIClient(api_base_url)

    st.title("📁 文档管理")

    # ── 上传区域 ──────────────────────────────────────────

    st.header("上传文档")
    st.caption("支持 PDF、DOCX、MD、TXT 格式，文件将自动解析、切块并入库。")

    # 上传配置
    col1, col2 = st.columns(2)
    with col1:
        department_id = st.selectbox(
            "部门",
            options=["public", "engineering", "hr", "finance", "sales", "legal"],
            help="选择文档所属部门，用于权限和检索过滤",
        )
    with col2:
        tags_input = st.text_input(
            "标签（逗号分隔）",
            placeholder="如：年报, 2024, 财务",
        )

    # 文件上传
    uploaded_files = st.file_uploader(
        "拖拽或点击上传文档",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
        help="单次可上传多个文件",
    )

    if uploaded_files:
        if st.button("🚀 提交入库", type="primary", use_container_width=True):
            tags = [t.strip() for t in tags_input.split(",") if t.strip()]

            for file in uploaded_files:
                _ingest_file(client, file, department_id, tags)

    # ── 状态查询 ──────────────────────────────────────────

    st.divider()
    st.header("查询文档状态")

    checksum_input = st.text_input(
        "输入文档 checksum（SHA-256）",
        placeholder="粘贴上传后返回的 checksum...",
    )
    if checksum_input.strip():
        if st.button("查询状态"):
            try:
                result = client.check_document_status(checksum_input.strip())
                if result.get("exists"):
                    st.success(f"文档已入库，共 {result.get('chunk_count', 0)} 个 chunk")
                else:
                    st.warning("文档未找到或尚未入库")
            except Exception as exc:
                st.error(f"查询失败：{exc}")


def _ingest_file(
    client: APIClient,
    file,
    department_id: str,
    tags: list[str],
) -> None:
    """上传单个文件并显示结果。"""
    file_bytes = file.read()

    status = st.status(f"处理中：{file.name}...", expanded=True)
    try:
        result = client.upload_document(
            file_bytes=file_bytes,
            filename=file.name,
            department_id=department_id,
            tags=tags,
        )
        status.update(label=f"✅ {file.name} — 入库成功", state="complete")
        status.write(f"**文件名**：{result.get('filename')}")
        status.write(f"**文档数**：{result.get('document_count')}")
        status.write(f"**Chunk 数**：{result.get('chunk_count')}")
        status.write(f"**Checksum**：`{result.get('checksum')}`")
    except Exception as exc:
        status.update(label=f"❌ {file.name} — 入库失败", state="error")
        status.write(str(exc))
