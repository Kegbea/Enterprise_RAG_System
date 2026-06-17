# ETL 管道

## 概述

ETL（Extract, Transform, Load）管道负责将原始文档转化为可供检索的向量化节点。

### 管道流程

```
原始文件 (bytes) → Parser → ParsedPage[] → Cleaner → ParsedPage[] → Chunker → TextNode[] → InMemoryDocStore
```

## 支持的文件格式

| 格式 | 扩展名 | 解析器 | 备注 |
|------|--------|--------|------|
| PDF | `.pdf` | `PDFParser` | 逐页解析，提取文本和表格 |
| Word | `.docx` | `DocxParser` | 提取段落、表格、样式 |
| Markdown | `.md` | `MarkdownParser` | 检测标题层级、Markdown 表格 |
| 纯文本 | `.txt` | `TxtParser` | 全文件作为单页处理 |

## 各阶段详解

### 1. Parser（解析器）

- 入口：`app/etl/parser.py`
- 工厂函数 `get_parser(filename)` 按扩展名分派
- 输出 `list[ParsedPage]`：每页含 text、tables（Markdown 格式）、headings

**PDF 特殊处理**：
- 使用 pdfplumber 逐页提取
- 自动检测表格并转换为 Markdown 格式
- 每页独立，保留页码信息

**表格占位符**：解析器在文本中插入 `[TABLE:N]` 标记，供分块器识别。

### 2. Cleaner（清洗器）

- `app/etl/cleaner.py` → `TextCleaner.clean(pages) → pages`
- 全角字符 → ASCII 半角（英文/数字）
- 移除控制字符（保留换行和制表符）
- 压缩多余空白（≥3 换行 → 2 换行，≥2 空格 → 1 空格）
- 移除空页

### 3. Chunker（分块器）

- `app/etl/chunker.py` → `TableAwareChunker`

**切块策略**：

| 策略 | 说明 |
|------|------|
| 表格原子性 | 检测到的表格作为完整 chunk，不切割 |
| 语义边界 | 优先在段落/句号处分块 |
| 硬截断 | 超过 chunk_size 的文本在句号处截断 |
| 父子节点 | 每页一个父节点关联所有子节点 |

**默认参数**：
- `chunk_size=512` tokens
- `chunk_overlap=50` tokens
- `max_table_rows=50`

**元数据注入**：每个 chunk 继承 `DocumentMetadata` 的全部字段，并附加页级别的 `heading_path`。

### 4. InMemoryDocStore

- `app/etl/pipeline.py` → `InMemoryDocStore`
- 基于 LlamaIndex `SimpleDocumentStore`
- 支持本地持久化（`data/storage/docstore.json`）
- 提供 ChromaDB 兼容接口：`add()`, `get()`, `delete()`, `count()`
- `get_all_nodes()` 返回全部 TextNode 供 RAG 检索器构建索引

## 去重机制

通过 SHA256 校验和实现文件级去重：

1. 上传时自动计算文件哈希
2. 查询存储中是否存在相同哈希
3. 存在且 `overwrite=False` → 跳过（status: "skipped"）
4. 存在且 `overwrite=True` → 删除旧节点后重新入库（status: "overwritten"）

## 使用示例

```python
from app.etl.pipeline import ETLPipeline, InMemoryDocStore

store = InMemoryDocStore(persist_dir="data/storage")
pipeline = ETLPipeline(store)

# 单文件入库
with open("document.pdf", "rb") as f:
    result = pipeline.ingest_bytes(f.read(), "document.pdf")

print(f"{result.status}: {result.chunks_created} chunks, {result.duration_ms:.0f}ms")

# 目录批量入库
batch = pipeline.ingest_directory(Path("data/documents/"))
print(f"{batch.succeeded}/{batch.total} succeeded")
```

## 添加新文件格式

1. 在 `app/etl/parser.py` 中创建新的 `XxxParser(BaseParser)` 子类
2. 实现 `parse(file_bytes, filename) -> list[ParsedPage]`
3. 在 `get_parser()` 中注册扩展名映射
4. 将新扩展名添加到 `ETLPipeline.SUPPORTED_EXTENSIONS`

```python
class HtmlParser(BaseParser):
    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]:
        # 解析逻辑
        return pages

# 注册
PARSER_REGISTRY["html"] = HtmlParser
```
