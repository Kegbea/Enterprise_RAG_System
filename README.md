# Enterprise RAG System

**企业级智能知识问答系统** — 基于 RAG（检索增强生成）架构的生产级实现。

## 架构概览

```
                        ┌──────────────┐
                        │  Streamlit   │  web_ui/ 前端
                        │    Web UI    │
                        └──────┬───────┘
                               │ HTTP/SSE
                        ┌──────▼───────┐
                        │   FastAPI    │  app/api/ 路由层
                        │  (CORS/Auth/ │  + 安全中间件
                        │ RateLimit/   │
                        │  AuditLog)   │
                        └──────┬───────┘
                               │
                 ┌─────────────┼─────────────┐
                 │             │             │
          ┌──────▼──────┐ ┌───▼───┐ ┌──────▼──────┐
          │ Ingestion   │ │ Query │ │    Eval     │
          │ Service     │ │Service│ │   Runner    │
          └──────┬──────┘ └───┬───┘ └──────┬──────┘
                 │             │             │
          ┌──────▼──────┐ ┌───▼────────────▼───┐
          │ ETL Pipeline│ │   RAG Engine       │
          │ parser →     │ │ HybridRetriever    │
          │ cleaner →    │ │  (BM25 + Dense +   │
          │ chunker →    │ │   RRF Fusion)      │
          │ docstore     │ │   ↓                │
          └──────┬──────┘ │ Reranker            │
                 │        │  (bge-reranker-v2)  │
                 │        │   ↓                │
                 └────────┤ QueryEngine         │
                          │  (LLM → SSE Stream) │
                          └─────────────────────┘
                                    │
                             ┌──────▼──────┐
                             │ InMemoryDoc │
                             │   Store     │
                             │ (LlamaIndex │
                             │ SimpleDoc-  │
                             │  Store)     │
                             └─────────────┘
```

**五阶段检索链路：**
```
用户问题 → BM25(关键词) + Dense(语义) → RRF融合 → bge-reranker精排 → LLM流式生成 → SSE推送 + 引用溯源
```

## 技术栈

| 层次 | 选型 |
|------|------|
| 环境管理 | uv + Python 3.12 |
| 后端框架 | FastAPI (async/await, SSE streaming) |
| RAG 编排 | LlamaIndex 0.12+ |
| 前端 | Streamlit 1.38+ |
| 向量模型 | text-embedding-v3 (DashScope) |
| LLM | qwen-plus (通义千问) |
| 重排序 | bge-reranker-v2-m3 (HuggingFace 本地) |
| 评估框架 | Ragas 0.2+ (五指标评估) |
| 文档解析 | pdfplumber + python-docx + 原生 MD/TXT |
| 中文分词 | jieba (BM25 tokenizer) |

## 核心功能

### 1. 离线 ETL 清洗链路
- **多格式解析**：PDF / DOCX / Markdown / TXT → 统一 Markdown 中间格式
- **表格感知**：表格原子保留（不分块），PDF/DOCX 表格提取为 Markdown Table
- **语义切块**：段落 > 句号 > 硬截断三级策略，表格段作为独立 Node
- **Parent-Child Node**：每页生成父节点，检索命中子节点时自动拉取完整上下文
- **清洗去噪**：全角→半角、控制字符过滤、空白压缩、空页过滤
- **去重机制**：SHA-256 checksum 去重，支持覆盖/跳过策略

### 2. 混合检索 + 重排序
- **BM25 关键词检索**：jieba 中文分词，解决 LlamaIndex 默认英文 tokenizer 对中文无效的问题
- **Dense 语义检索**：text-embedding-v3 向量相似度（embed_batch_size=10，符合 DashScope API 限制）
- **RRF 融合排序**：Reciprocal Rank Fusion（k=60），无需额外训练
- **bge-reranker 精排**：HuggingFace 本地加载，FlagEmbedding 不可用时自动降级为 pass-through

### 3. 流式问答 + 引用溯源
- **SSE 流式协议**：`text/event-stream`，事件类型 `citation → token × N → done`
- **引用卡片**：文件名 + 页码 + 标题路径 + 内容摘要，**全部从 metadata 提取**（不由 LLM 生成，避免幻觉引用）
- **对话历史**：SessionState 持久化，支持多轮对话上下文
- **引擎预检**：无文档时 `/api/chat/stream` 返回 503（而非在流中抛异常）

### 4. RAG 质量评估
- **五指标评估**：context_precision, context_recall, faithfulness, answer_relevancy, answer_correctness
- **Ragas 框架**：基于 Ragas 0.2+ 的标准化评估流程
- **CLI 工具**：`uv run python -m app.eval.cli`（真实 API 模式）或 `--mock` 模式（占位数据验证流程）
- **输出**：控制台报告 + 可选 JSON 文件导出

### 5. 安全防护
- **API Key 认证**：`X-API-Key` header 校验，`api_key` 为空时自动跳过（开发友好）
- **请求速率限制**：基于 IP 的滑动窗口限流（chat 30/min, upload 10/min, 默认 60/min）
- **审计日志**：记录 IP / method / path / status / 耗时 / auth 状态到独立 `audit` logger
- **文件上传限制**：单文件最大 50MB（可配置），超限返回 413
- **XSS 防护**：文档内容 `html.escape()` 转义后渲染
- **CORS 白名单**：显式来源列表，禁止 credentials + wildcard 组合
- **常量时间比较**：API Key 使用 `secrets.compare_digest` 防时序攻击

## 快速启动

```bash
# 1. 克隆 + 安装依赖
git clone <repo-url> && cd Enterprise_RAG_System
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY（从 https://dashscope.console.aliyun.com/apiKey 获取）
# 可选：设置 API_KEY 启用认证

# 3. 启动后端（终端 1）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. 启动前端（终端 2）
uv run streamlit run web_ui/app.py

# 5. 打开浏览器 http://localhost:8501
```

## 项目结构

```
Enterprise_RAG_System/
├── app/                          # FastAPI 后端
│   ├── main.py                   # 应用入口 (lifespan, 中间件链, 路由挂载)
│   ├── config.py                 # 统一配置中心 (pydantic-settings)
│   ├── api/                      # 路由 + 安全中间件
│   │   ├── chat.py               # POST /api/chat/stream (SSE)
│   │   ├── documents.py          # POST /api/documents/upload, GET /status/{checksum}
│   │   ├── auth.py               # API Key 认证中间件
│   │   ├── rate_limit.py         # 滑动窗口限流中间件
│   │   ├── audit.py              # 审计日志中间件
│   │   └── _utils.py             # 公共工具 (get_client_ip)
│   ├── services/                 # 业务逻辑层
│   │   ├── query_service.py      # RAG 引擎生命周期管理
│   │   └── ingestion.py          # 文档入库服务
│   ├── rag/                      # RAG 检索引擎
│   │   ├── hybrid_retriever.py   # BM25 + Dense + RRF 混合检索
│   │   ├── reranker.py           # bge-reranker 重排序器
│   │   └── query_engine.py       # 流式查询引擎 (检索→重排→LLM→SSE)
│   ├── etl/                      # ETL 清洗链路
│   │   ├── parser.py             # 文档解析器 (PDF/DOCX/MD/TXT)
│   │   ├── cleaner.py            # 文本清洗器
│   │   ├── chunker.py            # 表格感知切块器
│   │   └── pipeline.py           # ETL 编排器 + InMemoryDocStore
│   ├── eval/                     # 评估模块
│   │   ├── cli.py                # 命令行入口
│   │   ├── dataset.py            # 数据集加载
│   │   ├── metrics.py            # Ragas 指标配置
│   │   ├── runner.py             # 评估执行器
│   │   └── report.py             # 评估报告
│   └── models/                   # 数据模型
│       └── document.py           # DocumentMetadata, ChunkType, DocStatus
├── web_ui/                       # Streamlit 前端
│   ├── app.py                    # 应用入口 (侧边栏导航)
│   ├── chat.py                   # 聊天页 (流式对话 + 引用卡片)
│   ├── documents.py              # 文档管理页 (上传 + 状态查询)
│   └── api_client.py             # 后端 API 客户端 (HTTP/SSE)
├── scripts/                      # 运维脚本
│   └── ingest.py                 # 批量文档导入 CLI
├── tests/                        # 测试套件 (111 collected, 108 passed)
│   ├── test_parser.py            # 解析器测试
│   ├── test_cleaner.py           # 清洗器测试
│   ├── test_chunker.py           # 切块器测试
│   ├── test_pipeline.py          # ETL 管道测试
│   ├── test_models.py            # 数据模型测试
│   ├── test_rag.py               # RAG 检索 + 重排 + 查询引擎测试
│   ├── test_api_chat.py          # 聊天 API 测试
│   ├── test_api_documents.py     # 文档 API 测试
│   ├── test_ingestion_service.py # 入库服务测试
│   └── test_eval.py              # 评估模块测试
├── docs/                         # 技术文档
│   ├── index.md                  # 文档索引
│   ├── architecture.md           # 架构设计文档
│   ├── getting-started.md        # 入门指南
│   ├── configuration.md          # 配置参考
│   ├── api.md                    # API 参考
│   ├── etl.md                    # ETL 链路文档
│   └── evaluation.md             # 评估文档
├── data/                         # 持久化数据 (gitignored)
│   ├── chroma/                   # 向量数据库
│   ├── documents/                # 文档归档
│   ├── sessions/                 # 对话历史
│   ├── storage/                  # DocStore 持久化
│   └── eval/                     # 评估数据
├── .env.example                  # 环境变量模板
├── pyproject.toml                # 项目配置
├── uv.lock                       # 依赖锁定
└── README.md                     # 本文件
```

## API 端点

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| `GET` | `/health` | 健康检查（模型信息） | 无 |
| `GET` | `/docs` | Swagger 文档 | 无 |
| `POST` | `/api/chat/stream` | SSE 流式对话 | API Key |
| `POST` | `/api/documents/upload` | 上传文档入库 | API Key |
| `GET` | `/api/documents/status/{checksum}` | 查询文档状态 | API Key |

**SSE 事件类型：**

| 事件 | 数据结构 | 说明 |
|------|----------|------|
| `citation` | `{"sources": [{filename, page_number, heading_path, chunk_type, snippet}]}` | 检索引用声明 |
| `token` | `{"token": "文本增量"}` | LLM 流式生成的文本片段 |
| `done` | `{"status": "complete", "token_count": N}` | 生成结束信号 |

## 配置

所有配置通过 `.env` 文件管理，完整模板见 [`.env.example`](.env.example)。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | (必填) | DashScope API 密钥 |
| `LLM_MODEL` | `qwen-plus` | LLM 模型 |
| `EMBEDDING_MODEL` | `text-embedding-v3` | Embedding 模型 |
| `CHUNK_SIZE` | `512` | 切块大小 |
| `TOP_K` | `5` | 最终返回节点数 |
| `HYBRID_TOP_K` | `15` | 混合检索候选数 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排序模型 |
| `API_KEY` | (空) | 启用 API 认证时设置 |
| `CORS_ORIGINS` | `http://localhost:8501,...` | CORS 白名单 |
| `MAX_UPLOAD_SIZE_MB` | `50` | 单文件上传上限 |

## CLI 工具

```bash
# 批量导入文档
uv run python -m scripts.ingest --dir data/documents --overwrite

# RAG 评估（真实 API）
uv run python -m app.eval.cli --dataset data/eval/qa_pairs.json

# RAG 评估（Mock 模式，不调用 API）
uv run python -m app.eval.cli --mock --output report.json
```

## 测试

```bash
uv run pytest -v                        # 全部测试 (108 passed, 3 skipped)
uv run pytest -v --cov=app              # 带覆盖率报告
uv run pytest -m "not slow"             # 跳过集成测试
uv run pytest tests/test_rag.py -v      # 单文件测试
uv run ruff check .                     # Lint 检查
```

集成测试（标记 `slow`）需要 `DASHSCOPE_API_KEY` 环境变量，默认在 CI 中跳过。

## 安全

- API Key 认证（`X-API-Key` header，`secrets.compare_digest` 恒定时间比较）
- IP 滑动窗口速率限制（chat 30/min、upload 10/min、默认 60/min）
- 结构化审计日志（IP、method、path、status、latency、auth）
- CORS 来源白名单
- 文件上传大小限制（默认 50MB）
- 文档内容 HTML 转义（防 XSS）
- `.env` 已 gitignore，`.env.example` 仅含占位符

## 开发指南

- **Python 3.12**，`uv` 管理依赖，`ruff` 格式化（行宽 100）
- Pydantic v2 语法，`model_config` / `field_validator`
- FastAPI async/await 全链路，同步方法通过 `run_in_executor` 桥接
- 路由层薄如纸（仅参数校验 + 调 service），业务逻辑在 `app/services/`
- 全局配置单例 `from app.config import settings`，禁止 `os.getenv()` 散落
- 所有 `__init__.py` 为空文件

## License

MIT
