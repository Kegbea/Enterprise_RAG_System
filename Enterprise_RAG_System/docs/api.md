# API 参考

## 基础信息

- Base URL: `http://localhost:8000`
- Content-Type: `application/json`（除文件上传使用 `multipart/form-data`）
- 流式响应: `text/event-stream`

---

## GET /health

健康检查。

**响应** `200 OK`：

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "llm_model": "qwen-plus",
  "embedding_model": "text-embedding-v3"
}
```

---

## POST /api/chat/stream

流式问答接口，返回 SSE 事件流。

**请求体** `application/json`：

```json
{
  "query": "什么是混合检索？",
  "chat_history": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你？"}
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 用户问题（最少 1 字符） |
| `chat_history` | array | 否 | 对话历史，每个元素含 `role`（user/assistant）和 `content` |

**响应** `200 OK`（text/event-stream）：

```
event: citation
data: {"sources": [{"filename": "doc.pdf", "page_number": 3, "heading_path": "Chapter 1", "chunk_type": "text", "snippet": "前200字...", "node_id": "uuid"}]}

event: token
data: {"token": "混"}

event: token
data: {"token": "合"}

event: token
data: {"token": "检"}

...

event: done
data: {"status": "complete", "token_count": 42}
```

**事件类型**：

| 事件 | 触发时机 | payload |
|------|----------|---------|
| `citation` | 检索+重排完成后，生成开始前 | `{"sources": [...]}` |
| `token` | 每次 LLM 输出增量 | `{"token": "增量文本"}` |
| `done` | 生成完成 | `{"status": "complete", "token_count": N}` |

**citation source 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `filename` | string | 源文件名 |
| `page_number` | int\|null | 页码（PDF 有值，TXT/MD 为 null） |
| `heading_path` | string | 标题层级路径 |
| `chunk_type` | string | 块类型：text/table/heading/list/code |
| `snippet` | string | 文本前 200 字符摘要 |
| `node_id` | string | 节点 UUID |

**错误响应**：

- `422 Unprocessable Entity`：query 为空或格式错误
- `503 Service Unavailable`：引擎未就绪（无文档入库）

```json
{
  "detail": "RAG 引擎未就绪：请先上传文档。POST /api/documents/upload",
  "error_code": "ENGINE_NOT_READY"
}
```

---

## POST /api/documents/upload

文档上传入库。

**请求** `multipart/form-data`：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 文档文件（支持 PDF/DOCX/MD/TXT） |
| `department_id` | string | 否 | 部门标识（默认 "public"） |
| `tags` | string | 否 | 逗号分隔的标签（如 "财报,2024"） |
| `custom_metadata` | string | 否 | JSON 字符串格式的自定义元数据 |
| `overwrite` | string | 否 | "true" 则覆盖同名文档 |

**响应** `200 OK`：

```json
{
  "filename": "report.pdf",
  "status": "created",
  "chunks_created": 15,
  "checksum": "a1b2c3d4...",
  "error_message": "",
  "duration_ms": 1234.5
}
```

**status 值**：

| 值 | 说明 |
|------|------|
| `created` | 新建入库成功 |
| `skipped` | 检测到重复，已跳过 |
| `overwritten` | 覆盖入库成功 |
| `error` | 入库失败（见 error_message） |

---

## GET /api/documents/status/{checksum}

文档去重状态查询。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `checksum` | string | SHA256 校验和（64 位十六进制） |

**响应** `200 OK`：

```json
{
  "checksum": "a1b2c3d4...",
  "exists": true,
  "chunk_count": 15
}
```
