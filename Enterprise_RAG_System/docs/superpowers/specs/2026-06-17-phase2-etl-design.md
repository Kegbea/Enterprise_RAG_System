# 阶段二：ETL 文档解析与入库 — 设计规格

**日期：** 2026-06-17
**状态：** 已确认
**范围：** app/etl/ + app/models/document.py + app/services/ingestion.py + app/api/documents.py + scripts/ingest.py

---

## 1. 整体架构

```
                        ┌─────────────────────────┐
                        │    app/services/         │
                        │    ingestion.py          │  ← 公共业务逻辑
                        │    (解析+清洗+切块+入库)    │
                        └───────────┬─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ POST /api/     │   │ CLI: uv run    │   │ (未来) Kafka   │
     │ documents/     │   │ python -m      │   │ 消费者          │
     │ upload         │   │ scripts.ingest │   │                │
     └────────────────┘   └────────────────┘   └────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  Parser    │→│  Cleaner   │→│  Chunker   │→│ ChromaDB   │
     │ pdfplumber │ │ 去噪/标准化│ │ 表格感知   │ │ 持久化写入  │
     │ python-docx│ │            │ │ Parent-Child│ │            │
     │ markitdown │ │            │ │            │ │            │
     │ raw(text)  │ │            │ │            │ │            │
     └────────────┘  └────────────┘  └────────────┘  └────────────┘
```

### 文件结构

```
app/
  models/
    document.py          ← DocumentMetadata (Pydantic schema)
  etl/
    parser.py            ← parse_pdf / parse_docx / parse_md / parse_txt
    cleaner.py           ← TextCleaner: 去噪、标准化
    chunker.py           ← TableAwareChunker + Parent-Child Node 构建
    pipeline.py          ← ETLPipeline 编排器
  services/
    ingestion.py         ← IngestionService (公共入口, API/CLI 共用)
  api/
    documents.py         ← POST /api/documents/upload (薄路由)
scripts/
  ingest.py              ← CLI 批量导入入口
```

### 数据流（单文件处理）

```
bytes → detect file_type → 对应 parser → List[ParsedPage]
  → cleaner.clean(doc) → List[CleanedPage]
  → chunker.chunk(pages, metadata) → List[BaseNode]  (Parent + Child nodes)
  → checksum去重检查
  → chroma_store.add(nodes)
  → 返回 IngestResult (created / skipped / overwritten / error)
```

---

## 2. 元数据模型 DocumentMetadata

```python
# app/models/document.py

from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, model_validator
import hashlib

class ChunkType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"
    LIST = "list"
    CODE = "code"
    IMAGE_CAPTION = "image_caption"

class DocStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"

class DocumentMetadata(BaseModel):
    model_config = {"extra": "forbid"}

    # ── 基础字段 ──
    filename: str
    page_number: int | None = None
    heading_path: str = ""
    chunk_type: ChunkType = ChunkType.TEXT

    # ── 安全与权限 ──
    department_id: str = "public"

    # ── 工业运维字段 ──
    source: str = "api"
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    file_type: str = ""
    file_size: int = 0
    checksum: str = ""
    status: DocStatus = DocStatus.ACTIVE

    # ── 业务扩展 ──
    tags: list[str] = Field(default_factory=list)
    custom_metadata: dict[str, str] = Field(default_factory=dict)

    @staticmethod
    def compute_checksum(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @model_validator(mode="after")
    def _default_file_type_from_filename(self):
        if not self.file_type and self.filename:
            ext = self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""
            type_map = {"pdf": "pdf", "docx": "docx", "md": "md", "txt": "txt"}
            self.file_type = type_map.get(ext, "unknown")
        return self
```

### 去重逻辑

- 基于 `checksum`（SHA256）检查是否已存在相同文件
- `overwrite=False`：遇到重复跳过，返回 `status="skipped"`
- `overwrite=True`：删除旧 chunks，重新入库，返回 `status="overwritten"`

### 检索过滤契约（阶段四实现，此处预留）

```python
# POST /api/chat 请求中的 filters 字段，使用 LlamaIndex MetadataFilters
# 前端过滤条件示例:
# {"filters": [
#     {"key": "department_id", "value": "finance", "operator": "=="},
#     {"key": "tags", "value": "财报", "operator": "in"},
#     {"key": "status", "value": "active", "operator": "=="}
# ]}
```

---

## 3. 文档解析器

### 统一接口

```python
@dataclass
class ParsedPage:
    page_number: int
    text: str                    # 纯文本
    tables: list[str]            # Markdown table 格式
    headings: list[str]          # 该页检测到的标题

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> list[ParsedPage]: ...
    @abstractmethod
    def supported_extensions(self) -> list[str]: ...
```

### 四类解析器

| 解析器 | 依赖 | 表格提取方式 | 特殊处理 |
|--------|------|-------------|---------|
| `PDFParser` | pdfplumber | `page.extract_tables()` → Markdown Table | 按页遍历，表格区域标记 `[TABLE:N]` 占位符 |
| `DocxParser` | python-docx | 检测 `docx.table.Table` 节点 → Markdown Table | 段落样式识别标题层级（Heading 1-6） |
| `MarkdownParser` | markitdown | 正则匹配 `\|.*\|` 行 → 原样保留 | 解析 `#` 层级构建 heading_path |
| `TxtParser` | 内置 | 无 | 空行分段，无页码概念，page_number=None |

### 关键设计决策

1. **表格输出格式统一为 Markdown Table**，Chunker 只需识别一种格式
2. **PDF 表格区域标记** — 替换原位置为 `[TABLE:N]` 占位符，表格内容存入 `ParsedPage.tables[N]`
3. **标题路径累积** — 解析过程中维护标题栈，自动构建 `heading_path`（如 `第1章 > 1.1 概述 > 1.1.2 财务数据`）
4. **空页/纯图片页过滤** — Cleaner 阶段移除无文本且无表格的页

---

## 4. Cleaner + Table-Aware Chunker

### Cleaner

- **职责：** 纯文本清洗，无状态
- **步骤：** 全角半角统一 → 多余空白压缩 → 乱码字符过滤 → 空段落移除 → 过滤空页
- **表格清洗：** 去除表格内多余空格，统一分隔符

### Table-Aware Chunker — 核心设计

**切块流程：**

```
一页文档文本 → [TABLE:N] 占位符分割 → 逐段判断类型 →
  ├─ 表格段: 创建 table chunk (atomic, 不切分)
  └─ 文本段: 按语义边界切分 (chunk_size=512, overlap=50)

该页所有子节点 → 构建 Parent Node (整页文本作为上下文)
```

**Parent-Child 关系（LlamaIndex 原生）：**

```python
# Child → Parent
child_node.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(
    node_id=parent_node.node_id)

# Parent → Children
parent_node.relationships[NodeRelationship.CHILD] = [
    RelatedNodeInfo(node_id=c.node_id) for c in child_nodes]

# 检索行为：命中 child → 自动拉取 parent → 返回完整上下文
```

**表格原子保留规则：**
- `chunk_type=table`，不参与 `chunk_size` 切分
- 超过 `max_table_rows=50` 时记录 warning，但仍原子保留
- 嵌入时表格 Markdown 文本直接送入 embedding 模型

**语义边界切分优先级：**
1. `\n\n`（段落边界）
2. `。`（句号）
3. `\n`（换行）
4. `chunk_size` 硬截断 + `chunk_overlap` 重叠

### Future Work（后续优化，不在本次实现范围）

- **B) 大表格行列切分**：超过 N 行的表格按行切分为多个子表格 chunk，每个子表格携带完整表头
- **C) 表格摘要嵌入**：用 LLM 生成表格摘要替代原始表格做 embedding，检索命中后从元数据还原完整表格

---

## 5. Pipeline 编排 + IngestionService + 双入口

### ETLPipeline

```python
class ETLPipeline:
    def ingest_bytes(
        self, file_bytes: bytes, filename: str,
        metadata_overrides: DocumentMetadata | None = None,
        overwrite: bool = False,
    ) -> IngestResult:
        """处理单个文件 bytes → 入库"""

    def ingest_directory(
        self, dir_path: Path, overwrite: bool = False
    ) -> BatchIngestResult:
        """扫描目录批量入库"""
```

`IngestResult` 字段：`filename`, `status` (created/skipped/overwritten/error), `chunks_created`, `checksum`, `error_message`, `duration_ms`

`BatchIngestResult` 字段：`total`, `succeeded`, `skipped`, `overwritten`, `failed`, `items: list[IngestResult]`

### IngestionService

```python
class IngestionService:
    async def ingest_upload(
        self, file: UploadFile,
        department_id: str = "public",
        tags: list[str] | None = None,
        custom_metadata: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> IngestResult: ...

    def ingest_batch(
        self, dir_path: Path | None = None, overwrite: bool = False
    ) -> BatchIngestResult: ...
```

### API 薄路由（app/api/documents.py）

- `POST /api/documents/upload` — 上传文档并入库
- `GET /api/documents/status/{checksum}` — 检查文档是否已入库

### CLI 批量导入（scripts/ingest.py）

```bash
uv run python -m scripts.ingest --dir data/documents --overwrite
```

### 生命周期集成

在 `app/main.py` lifespan startup 中初始化 ChromaDB client → Collection → ETLPipeline → IngestionService，挂到 `app.state`。

### 错误处理策略

| 场景 | 行为 |
|------|------|
| 不支持的文件类型 | `status="error"`, 不阻塞批量任务 |
| 文件损坏/解析失败 | 捕获异常，记录 error 日志，不阻塞批量任务 |
| checksum 重复 + overwrite=False | `status="skipped"` |
| checksum 重复 + overwrite=True | 删除旧 chunks + 重新入库，`status="overwritten"` |
| ChromaDB 写入失败 | 重试 3 次后 `status="error"` |

---

## 6. 测试策略

| 测试层级 | 覆盖内容 |
|---------|---------|
| 单元测试 | 每个 parser 的解析正确性（用 fixtures 目录下的样本文件） |
| 单元测试 | TextCleaner 各种清洗场景 |
| 单元测试 | TableAwareChunker 表格检测、原子保留、Parent-Child 关系 |
| 单元测试 | DocumentMetadata schema 校验、checksum 计算 |
| 集成测试 | ETLPipeline.ingest_bytes() 完整链路（解析→清洗→切块→入库→去重） |
| 集成测试 | IngestionService 上传 + 批量导入 |
| API 测试 | POST /api/documents/upload 成功/失败/去重场景 |

---

## 7. 依赖项（已就位）

阶段二所有依赖已在 `pyproject.toml` 中声明：
- `pdfplumber>=0.11.0` — PDF 解析
- `python-docx>=1.1.0` — DOCX 解析
- `markitdown>=0.1.0` — Markdown 解析
- `chromadb>=0.5.0` — 向量数据库
- `llama-index-core>=0.12.0` — Node 类型、Parent-Child 关系
- `llama-index-vector-stores-chroma>=0.4.0` — ChromaDB 集成
- `jieba>=0.42.0` — 中文分词（BM25 阶段三使用）
- `pydantic-settings>=2.5.0` — 配置管理
