# 配置说明

## 配置文件

所有配置通过 `.env` 文件设置，由 `app/config.py` (`pydantic-settings`) 加载。

## 配置项一览

### 核心配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DASHSCOPE_API_KEY` | (必填) | DashScope API 密钥，用于 LLM 和 Embedding |
| `LLM_MODEL` | `qwen-plus` | LLM 模型名称 |
| `LLM_TEMPERATURE` | `0.1` | 生成温度（0-1），越低越确定 |
| `EMBEDDING_MODEL` | `text-embedding-v3` | Embedding 模型名称 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 重排序模型（HuggingFace） |

### 检索参数

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `TOP_K` | `5` | 最终返回给 LLM 的节点数 |
| `HYBRID_TOP_K` | `15` | BM25/Dense/RRF 中间的检索数量 |

### 存储路径

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `STORAGE_DIR` | `data/storage` | InMemoryDocStore 持久化目录 |
| `DOCUMENT_ARCHIVE_DIR` | `data/documents` | 上传原始文件归档目录 |
| `SESSION_DIR` | `data/sessions` | 对话历史存储目录 |
| `CHROMA_PERSIST_DIR` | `data/chroma` | ChromaDB 目录（预留） |

### ETL 参数

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `CHUNK_SIZE` | `512` | 分块大小（tokens） |
| `CHUNK_OVERLAP` | `50` | 相邻块重叠大小（tokens） |

### 服务配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `API_HOST` | `0.0.0.0` | FastAPI 监听地址 |
| `API_PORT` | `8000` | FastAPI 监听端口 |

## 推荐配置

### 开发环境

```env
DASHSCOPE_API_KEY=sk-xxx
LLM_TEMPERATURE=0.1
CHUNK_SIZE=512
HYBRID_TOP_K=15
TOP_K=5
```

### 生产环境

```env
DASHSCOPE_API_KEY=sk-xxx
LLM_MODEL=qwen-plus
LLM_TEMPERATURE=0.0
CHUNK_SIZE=512
CHUNK_OVERLAP=50
TOP_K=5
HYBRID_TOP_K=20
```

## 参数调优建议

### 分块大小（chunk_size）

- **512**：通用推荐，平衡语义完整性和检索精度
- **256**：适合短问答场景，检索粒度更细
- **1024**：适合长文档理解，语义更完整但检索精度下降

### 检索数量（top_k / hybrid_top_k）

- **top_k=5**：适合大多数问答场景
- **top_k=10**：需要更多上下文时使用
- **hybrid_top_k=15-20**：给重排序足够的候选池

### LLM 温度（temperature）

- **0.0-0.1**：企业知识问答推荐，减少幻觉
- **0.3-0.5**：需要更多创造性时使用
- **0.7-1.0**：不适合 RAG 场景，容易偏离来源

## 配置优先级

pydantic-settings 按以下优先级加载配置（高到低）：

1. 环境变量（`export DASHSCOPE_API_KEY=xxx`）
2. `.env` 文件
3. 代码中指定的默认值

## 代码中访问配置

```python
from app.config import settings

# 单例模式，全局唯一
model = settings.llm_model  # "qwen-plus"
top_k = settings.top_k      # 5
```

**禁止**在业务代码中使用 `os.getenv()` 直接读取配置——统一通过 `settings` 单例。
