# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
uv sync                          # 安装/同步所有依赖（含 dev）
uv sync --no-dev                 # 仅生产依赖
uv run uvicorn app.main:app --reload   # 启动 FastAPI 后端
uv run streamlit run web_ui/app.py     # 启动 Streamlit 前端
uv run pytest -v                 # 运行全部测试
uv run pytest -v --cov=app       # 带覆盖率
uv run pytest tests/test_parser.py -v  # 单文件测试
uv run ruff check .              # lint 检查
uv run ruff format .             # 代码格式化
```

## 架构分层

```
web_ui/ (Streamlit) ──HTTP/SSE──▶ app/api/ (薄路由) ──▶ app/services/ (业务逻辑)
                                                              │
                                     app/rag/ (检索) ◀────────┤
                                     app/etl/ (入库) ◀────────┘
```

**四个核心层，从上到下：**

1. **`app/api/`** — FastAPI 路由层。**薄如纸**：只做参数校验 + 调 service + 返回响应。不含任何业务逻辑。
2. **`app/services/`** — 业务逻辑层。可被多个 router 复用，可脱离 HTTP 独立测试。
3. **`app/rag/`** — RAG 检索链路。检索策略（hybrid_retriever / reranker）和查询引擎（query_engine）独立于 API 层，可单独命令行调试。
4. **`app/etl/`** — ETL 离线清洗链路。parser → cleaner → chunker → pipeline，每步职责单一。

**关键设计决策：**

- `app/config.py`：用 `pydantic-settings` 强类型配置，禁止在业务代码中 `os.getenv()`。全局单例 `from app.config import settings`。
- `app/main.py`：`lifespan` 事件中初始化持久化目录和 RAG 引擎全局实例（挂到 `app.state`），shutdown 时清理。
- 中文分词：jieba 替换 LlamaIndex BM25 默认英文 tokenizer。所有 BM25 相关代码必须显式传入 `tokenizer=chinese_tokenizer`。
- 引用追踪：检索结果的 `node.metadata` 携带 `filename`、`page_number`、`heading_path`、`chunk_type`、`department_id` 等字段，前端引用卡片和流式响应的 citation 事件均从 metadata 提取——**不由 LLM 生成**。
- SSE 流式协议：`POST /api/chat/stream` 响应 `text/event-stream`，事件类型含 `token`（流式文本）、`citation`（引用来）、`done`（结束信号）。

## 当前开发阶段

**阶段一已完成**（环境奠基）：pyproject.toml、config、FastAPI /health 端点可启动。

**待开发：**
- 阶段二：app/etl/（PDF/DOCX/MD/TXT 解析 + 表格感知切块 + 元数据注入 + ChromaDB 入库）
- 阶段三：app/rag/（BM25+Dense 混合检索 + RRF + bge-reranker + 流式查询引擎）
- 阶段四：app/api/ 路由 + app/services/ + web_ui/ Streamlit 前端
- 阶段五：Ragas 评估 + docs/

## 模型与 API

- LLM: qwen-plus（通过 `llama-index-llms-dashscope`）
- Embedding: text-embedding-v3（通过 `llama-index-embeddings-dashscope`）
- API Key: `.env` 中 `DASHSCOPE_API_KEY`，当前为占位值，需用户填入真实 key
- 重排序: bge-reranker-v2-m3（HuggingFace 本地加载，首次运行自动下载）

## 代码规范

- Python 3.12，uv 管理依赖，ruff 格式化（行宽 100）
- 所有 `__init__.py` 为空文件
- Pydantic v2 语法（`model_config`、`field_validator`），禁用 v1 风格
- 异步全链路：FastAPI async/await → LlamaIndex `aquery()` → SSE 流式响应

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发，或在执行实现计划之前使用——通过原生工具或 git worktree 回退机制确保隔离工作区存在
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
