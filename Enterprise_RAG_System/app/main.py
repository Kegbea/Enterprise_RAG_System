"""FastAPI 应用入口 — 生命周期管理 + 路由挂载。

设计原则：
- 路由层薄如纸，只做参数校验和响应序列化
- 业务逻辑下沉到 app/services/
- 全局单例（RAG 引擎）通过 lifespan 事件初始化和销毁
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    startup:  初始化目录、加载模型（阶段三后启用）
    shutdown: 清理资源
    """
    # === Startup ===
    # 确保必要的持久化目录存在
    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    settings.document_archive_path.mkdir(parents=True, exist_ok=True)
    settings.session_path.mkdir(parents=True, exist_ok=True)

    # 初始化 ETL Pipeline + IngestionService
    from app.etl.pipeline import ETLPipeline, InMemoryDocStore
    from app.services.ingestion import IngestionService

    store = InMemoryDocStore()
    pipeline = ETLPipeline(store)
    app.state.ingestion_service = IngestionService(
        pipeline=pipeline,
        archive_dir=settings.document_archive_path,
    )

    yield  # ← 应用运行期间

    # === Shutdown ===
    pass


app = FastAPI(
    title="Enterprise RAG System",
    description="企业级智能知识问答系统 — 基于 LlamaIndex + DashScope + ChromaDB",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — 允许 Streamlit 前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
from app.api.documents import router as documents_router  # noqa: E402

app.include_router(documents_router)
