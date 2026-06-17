# 快速上手

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- [DashScope API Key](https://dashscope.console.aliyun.com/)（用于 LLM 和 Embedding）

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd Enterprise_RAG_System

# 安装依赖（含开发依赖）
uv sync
```

## 配置

创建 `.env` 文件（项目根目录）：

```env
DASHSCOPE_API_KEY=sk-your-api-key-here
```

这是**唯一必需的**环境变量。其他配置项有合理默认值，详见[配置说明](configuration.md)。

## 启动

### 方式一：分别启动

```bash
# 终端 1：启动 FastAPI 后端
uv run uvicorn app.main:app --reload

# 终端 2：启动 Streamlit 前端
uv run streamlit run web_ui/app.py
```

### 方式二：仅后端（纯 API）

```bash
uv run uvicorn app.main:app --reload
```

后端启动后，可通过 `http://localhost:8000/docs` 访问 Swagger UI 交互式 API 文档。

## 验证

```bash
# 健康检查
curl http://localhost:8000/health
# → {"status":"healthy","version":"0.1.0","llm_model":"qwen-plus",...}

# 上传测试文档
curl -X POST http://localhost:8000/api/documents/upload \
  -F "file=@data/eval/sample_knowledge.md" \
  -F "department_id=engineering"

# 流式问答
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"什么是 RAG？"}' \
  --no-buffer
```

## 首次使用

1. 打开浏览器访问 `http://localhost:8501`
2. 确认侧边栏后端地址为 `http://localhost:8000`
3. 点击"健康检查"确认连接正常
4. 切换到"文档管理"页面上传文档
5. 切换到"智能问答"页面开始提问

## 命令行工具

### 文档入库

```bash
# 单文件
uv run python scripts/ingest.py --file path/to/document.pdf

# 目录批量入库
uv run python scripts/ingest.py --dir path/to/docs/
```

### 评估

```bash
# Mock 模式（不调用 API，验证流程）
uv run python -m app.eval.cli --mock

# 完整评估（需要 API key）
uv run python -m app.eval.cli --dataset data/eval/qa_pairs.json
```

见[评估指南](evaluation.md)。

## 运行测试

```bash
# 全量测试
uv run pytest -v

# 含覆盖率
uv run pytest -v --cov=app

# 跳过慢速/集成测试
uv run pytest -m "not slow"

# 仅评估模块测试
uv run pytest tests/test_eval.py -v
```
