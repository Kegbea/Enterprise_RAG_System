"""FastAPI 应用入口 — 生命周期管理 + 路由挂载。

设计原则：
- 路由层薄如纸，只做参数校验和响应序列化
- 业务逻辑下沉到 app/services/
- 全局单例（RAG 引擎）通过 lifespan 事件初始化和销毁
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import AuditLogMiddleware
from app.api.auth import APIKeyMiddleware
from app.api.rate_limit import RateLimitMiddleware
from app.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    startup:  初始化目录、加载模型、构建 RAG 引擎
    shutdown: 持久化存储、清理资源
    """
    # === Startup ===
    # 确保必要的持久化目录存在
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    settings.document_archive_path.mkdir(parents=True, exist_ok=True)
    settings.session_path.mkdir(parents=True, exist_ok=True)

    # 1. 持久化文档存储
    from app.etl.pipeline import ETLPipeline, InMemoryDocStore

    store = InMemoryDocStore(persist_dir=settings.storage_dir)

    # 2. ETL Pipeline + IngestionService
    pipeline = ETLPipeline(store)
    from app.services.ingestion import IngestionService

    ingestion_service = IngestionService(
        pipeline=pipeline,
        archive_dir=settings.document_archive_path,
    )
    app.state.ingestion_service = ingestion_service

    # 3. RAG 查询服务（传入 store，支持后续懒初始化）
    from app.services.query_service import QueryService

    query_service = QueryService(store)
    app.state.query_service = query_service

    # 4. 绑定回调：入库成功后自动刷新检索索引
    ingestion_service.set_on_ingested(query_service.refresh)

    yield  # ← 应用运行期间

    # === Shutdown ===
    # 退出前落盘，确保所有数据持久化
    if hasattr(app.state, "ingestion_service"):
        app.state.ingestion_service.pipeline.store.persist()
        logger.info("Storage persisted on shutdown")


app = FastAPI(
    title="Enterprise RAG System",
    description="企业级智能知识问答系统 — 基于 LlamaIndex + DashScope + ChromaDB",
    version="0.1.0",
    lifespan=lifespan,
)

# 中间件顺序（Starlette LIFO — 后添加先执行）：
# 请求链：AuditLog → RateLimit → Auth → CORS → handler
# 响应链：handler → CORS → Auth → RateLimit → AuditLog

# 1. CORS — 最内层，确保跨域头最后写入
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# 2. API Key 认证 — 对所有 /api/* 路由生效（api_key 为空时跳过）
app.add_middleware(APIKeyMiddleware)

# 3. 速率限制 — 在认证之后、审计之前，防止暴力破解
app.add_middleware(RateLimitMiddleware)

# 4. 审计日志 — 最外层，记录所有请求（含被限流/认证拒绝的请求）
app.add_middleware(AuditLogMiddleware)


# ── 健康检查端点 ──
@app.get("/health")
async def health_check():
    """系统健康检查。

    Kubernetes liveness probe 标准端点，面试时可以说你考虑了云原生部署。
    """
    return {
        "status": "healthy",
        "version": "0.1.0",
        "llm_model": settings.llm_model,
        "embedding_model": settings.embedding_model,
    }


# ── 挂载路由（import 必须在 app 创建之后，因为 router 依赖 app.state） ──
from app.api.chat import router as chat_router  # noqa: E402
from app.api.documents import router as documents_router  # noqa: E402

app.include_router(chat_router)
app.include_router(documents_router)
