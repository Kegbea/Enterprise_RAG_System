# 企业 RAG 系统 — 文档目录

## 系统文档

| 文档 | 说明 |
|------|------|
| [快速上手](getting-started.md) | 环境安装、配置、启动和第一个问答 |
| [系统架构](architecture.md) | 五层架构设计、数据流、关键设计决策 |
| [API 参考](api.md) | REST API 端点、SSE 协议、请求/响应格式 |
| [ETL 管道](etl.md) | 文档解析、清洗、分块策略、入库流程 |
| [配置说明](configuration.md) | 全部配置项、参数调优建议 |
| [评估指南](evaluation.md) | Ragas 评估指标、数据集准备、运行与解读 |

## 项目结构

```
Enterprise_RAG_System/
├── app/
│   ├── api/          # FastAPI 路由层
│   ├── services/     # 业务逻辑层
│   ├── rag/          # RAG 检索链路
│   ├── etl/          # ETL 离线清洗链路
│   ├── eval/         # 评估模块
│   └── models/       # 数据模型
├── web_ui/           # Streamlit 前端
├── data/
│   ├── eval/         # 评估数据集
│   ├── storage/      # 向量存储持久化
│   └── documents/    # 原始文件归档
├── tests/            # 测试
└── docs/             # 文档
```

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM | qwen-plus（DashScope） |
| Embedding | text-embedding-v3（DashScope） |
| Reranker | bge-reranker-v2-m3（HuggingFace） |
| 检索 | BM25 + Dense + RRF 融合 |
| 向量索引 | LlamaIndex VectorStoreIndex |
| 后端 | FastAPI + SSE 流式响应 |
| 前端 | Streamlit |
| 评估 | Ragas |
| 分词 | jieba（中文） |
