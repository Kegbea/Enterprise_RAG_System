# 系统架构

## 架构分层

系统采用五层架构设计，自上而下为：

```
web_ui/ (Streamlit) ──HTTP/SSE──▶ app/api/ (薄路由) ──▶ app/services/ (业务逻辑)
                                                             │
                                    app/rag/ (检索) ◀────────┤
                                    app/etl/ (入库) ◀────────┘
```

### 第 1 层：Web UI

[web_ui/](../web_ui/) — Streamlit 前端，提供两大页面：

- **智能问答**（chat.py）：流式对话界面，实时显示 LLM 回答和引用卡片
- **文档管理**（documents.py）：文件上传、去重检测、入库状态查询

通过 `api_client.py` 封装后端 HTTP 调用，支持 SSE 流式解析。

### 第 2 层：API 路由

[app/api/](../app/api/) — FastAPI 薄路由层，**不含业务逻辑**：

- `POST /api/chat/stream` — SSE 流式问答（含 503 预检）
- `POST /api/documents/upload` — 文档上传入库
- `GET /api/documents/status/{checksum}` — 去重状态查询
- `GET /health` — 健康检查

### 第 3 层：业务服务

[app/services/](../app/services/) — 业务逻辑编排：

- **QueryService**：RAG 引擎生命周期管理（延迟初始化 + 自动刷新）
- **IngestionService**：文档入库编排，支持单文件和批量模式

### 第 4 层：RAG 检索链路

[app/rag/](../app/rag/) — 核心检索链路：

```
用户查询 → BM25 检索 + Dense 检索 → RRF 融合 → bge-reranker 精排 → LLM 生成 → SSE 流式输出
```

- **HybridRetriever**：BM25（jieba 分词）+ Dense（向量检索）+ RRF 融合
- **Reranker**：bge-reranker-v2-m3 语义精排，不可用时自动降级为 pass-through
- **QueryEngine**：检索 → 重排 → LLM → SSE 全链路

### 第 5 层：ETL 管道

[app/etl/](../app/etl/) — 离线文档处理管道：

```
原始文件 → Parser → Cleaner → Chunker → InMemoryDocStore
```

## 数据流

### 上传流程

```
用户上传文件 → API 校验 → 计算 SHA256 → 去重检查
    → Parser 解析 → Cleaner 清洗 → Chunker 分块
    → InMemoryDocStore 入库 → 触发 QueryService.refresh()
    → HybridRetriever 重建索引
```

### 问答流程

```
用户提问 → QueryService.query_stream()
    → HybridRetriever.retrieve() (BM25 + Dense + RRF)
    → Reranker.rerank() (bge-reranker 精排 top_n=5)
    → 提取 citations (from metadata, 非 LLM 生成)
    → 构建 LLM 上下文 (SYSTEM + HISTORY + USER)
    → DashScope.astream_chat() 流式生成
    → SSE 事件流: citation → token×N → done
```

## 关键设计决策

### 引用追踪

检索结果的 `node.metadata` 携带 `filename`、`page_number`、`heading_path`、`chunk_type` 等字段。前端引用卡片和 SSE citation 事件均从 metadata 提取——**不由 LLM 生成**，从根本上杜绝幻觉引用。

### 延迟初始化

QueryService 采用 lazy init 策略：引擎仅在首次查询或 refresh 时才构建索引。避免启动时无文档或 API key 无效导致的崩溃。

### 中文分词

BM25 使用 jieba 分词器替换 LlamaIndex 默认英文 tokenizer。所有 BM25 相关代码显式传入 `tokenizer=chinese_tokenizer`。

### SSE 流式协议

`POST /api/chat/stream` 响应 `text/event-stream`，事件类型：
- `citation`：引用来源声明
- `token`：流式文本增量（可出现 0~N 次）
- `done`：结束信号（含 token_count）

### 表格原子性

ETL 管道检测到的表格作为完整 chunk 保留，不做切割。表格占位符 `[TABLE:N]` 由解析器插入，分块器识别后保持完整性。

### 父子节点

每页创建一个父节点，关联该页所有子节点。检索命中子节点时，可通过 parent 关系回溯完整页面上下文。
