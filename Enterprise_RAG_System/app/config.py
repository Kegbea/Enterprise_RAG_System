"""统一配置中心 — 基于 pydantic-settings 的强类型配置。

所有环境变量在此集中校验，启动时缺失则立即报错，而非在业务代码中静默失败。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置，自动从 .env 文件和环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── DashScope API ──
    dashscope_api_key: str
    llm_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"

    # ── ChromaDB ──
    chroma_persist_dir: str = "data/chroma"
    chroma_collection_name: str = "enterprise_knowledge"

    # ── 持久化存储 ──
    storage_dir: str = "data/storage"

    # ── 重排序模型 ──
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ── 文档存储 ──
    document_archive_dir: str = "data/documents"

    # ── 对话历史 ──
    session_dir: str = "data/sessions"

    # ── Chunking 参数 ──
    chunk_size: int = 512
    chunk_overlap: int = 50

    # ── 检索参数 ──
    top_k: int = 5
    hybrid_top_k: int = 15

    # ── 服务 ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    ui_port: int = 8501

    @property
    def chroma_path(self) -> Path:
        """ChromaDB 持久化目录的绝对路径。"""
        return Path(self.chroma_persist_dir).resolve()

    @property
    def document_archive_path(self) -> Path:
        """文档归档目录的绝对路径。"""
        return Path(self.document_archive_dir).resolve()

    @property
    def session_path(self) -> Path:
        """会话数据目录的绝对路径。"""
        return Path(self.session_dir).resolve()


# 全局单例 — 整个 app 通过 `from app.config import settings` 引用
settings = Settings()
