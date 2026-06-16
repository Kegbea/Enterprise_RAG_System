# Enterprise RAG System

**企业级智能知识问答系统** — 基于 RAG（检索增强生成）架构的生产级实现。

## 架构概览

```
Document Upload → ETL Pipeline → ChromaDB
                                      ↓
User Question   → HybridSearch → Reranker → LLM (Streaming) → Answer + Citations
                (BM25 + Dense)   (bge-reranker)  (通义千问)
```

## 技术栈

| 层次 | 选型 |
|------|------|
| 环境管理 | uv + Python 3.12 |
| 后端框架 | FastAPI (async/await) |
| RAG 编排 | LlamaIndex |
| 向量数据库 | ChromaDB |
| 前端 | Streamlit |
| 评估 | Ragas |
| 模型 | 通义千问 (DashScope API) |

## 核心功能

1. **离线 ETL 清洗链路**：PDF/DOCX/MD/TXT → Markdown（保留表格结构）→ 智能切块 → 向量化入库
2. **混合检索 + 重排序**：BM25（Jieba 分词）+ Dense（向量相似度）+ RRF 融合 + bge-reranker 精排
3. **流式问答 + 引用溯源**：SSE 流式输出，前端展示精确引用来源（源文件、匹配得分、文本片段）

## 快速启动

```bash
# 1. 环境准备
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 3. 启动后端
uv run uvicorn app.main:app --reload

# 4. 启动前端（新终端）
uv run streamlit run web_ui/app.py
```

## 项目结构

```
app/         FastAPI 后端 (config, models, etl, rag, api, services)
web_ui/      Streamlit 前端 (pages, components)
data/        持久化数据 (chroma, documents, sessions, eval)
tests/       测试套件
scripts/     运维脚本 (评估、数据导入)
docs/        技术文档
```
