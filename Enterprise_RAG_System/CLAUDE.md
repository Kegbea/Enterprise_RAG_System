# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
uv sync                          # 安装/同步所有依赖（含 dev）
uv sync --no-dev                 # 仅生产依赖
uv run uvicorn app.main:app --reload   # 启动 FastAPI 后端
uv run streamlit run web_ui/app.py     # 启动 Streamlit 前端
uv run pytest -v                 # 运行全部测试（111 collected, 108 passed, 3 skipped）
uv run pytest -v --cov=app       # 带覆盖率
uv run pytest tests/test_parser.py -v  # 单文件测试
uv run pytest -m "not slow"      # 跳过慢速测试
uv run ruff check .              # lint 检查
uv run ruff format .             # 代码格式化
uv run python -m scripts.ingest --dir data/documents  # 批量导入文档
uv run python -m app.eval.cli --mock                  # Mock 评估（不调用 API）
uv run python -m app.eval.cli --output report.json    # 真实评估 + JSON 报告
```

## 架构分层

```
web_ui/ (Streamlit) ──HTTP/SSE──▶ app/api/ (薄路由) ──▶ app/services/ (业务逻辑)
                                                             │
                                    app/rag/ (检索) ◀────────┤
                                    app/etl/ (入库) ◀────────┘
                                    app/eval/ (评估)         独立模块
```

**五层结构，从上到下：**

1. **`web_ui/`** — Streamlit 前端。侧边栏导航，聊天页（流式+引用卡片）、文档管理页。通过 `api_client.py` 封装后端调用，`X-API-Key` header 自动注入。
2. **`app/api/`** — FastAPI 路由 + 安全中间件层。
   - 路由：`chat.py`（SSE 流式对话，含 503 预检）、`documents.py`（上传+状态查询）
   - 中间件：`auth.py`（API Key 认证，`secrets.compare_digest` 恒定时间比较）、`rate_limit.py`（IP 滑动窗口限流，惰性启动）、`audit.py`（结构化审计日志）
   - 公共工具：`_utils.py`（`get_client_ip` 等复用函数）
   - **薄如纸**：只做参数校验/安全检查 + 调 service + 返回响应。不含任何业务逻辑。
3. **`app/services/`** — 业务逻辑层。`QueryService` 管理 RAG 引擎生命周期（延迟初始化 + 自动刷新），`IngestionService` 管理文档入库（`ingest_upload` / `ingest_bytes` / `ingest_batch`）。可脱离 HTTP 独立测试。
4. **`app/rag/`** — RAG 检索链路。`HybridRetriever`(BM25+Dense+RRF) → `Reranker`(bge-reranker/pass-through) → `QueryEngine`(检索→重排→LLM→SSE)。可单独命令行调试。
5. **`app/etl/`** — ETL 离线清洗链路。parser → cleaner → chunker → pipeline，每步职责单一。存储基于 `InMemoryDocStore`(LlamaIndex SimpleDocumentStore + 本地持久化)。
6. **`app/eval/`** — RAG 评估模块。dataset → metrics → runner → report → CLI，基于 Ragas 五指标评估检索和生成质量。支持 `--mock` 模式（不调用 API 验证流程）。

**关键设计决策：**

- `app/config.py`：用 `pydantic-settings` 强类型配置，禁止在业务代码中 `os.getenv()`。全局单例 `from app.config import settings`。
- `app/main.py`：`lifespan` 事件中初始化持久化目录、ETL Pipeline、IngestionService、QueryService，绑定回调链（入库→刷新索引），shutdown 时落盘。
- **中间件链**（Starlette LIFO — 后添加先执行）：`AuditLog(最外层) → RateLimit → Auth → CORS(最内层) → handler`。限流在认证之前防暴力破解，审计在最外层捕获所有请求。
- **API Key 认证**：`auth.py` 仅对 `/api/*` 路径生效，`settings.api_key` 为空时跳过。使用 `secrets.compare_digest` 恒定时间比较防时序攻击。
- **速率限制**：`rate_limit.py` 滑动窗口（60s）+ IP 维度，chat 30/min、upload 10/min、默认 60/min。定时清理惰性启动（首次 dispatch 时），每个 IP 时间戳上限 200。
- **审计日志**：`audit.py` 记录 IP、method、path、status、duration、user_agent、auth_status 到独立 `audit` logger，可独立配置 handler。
- **文件上传安全**：路由层先读 bytes 做大小检查（413 超限），直接传 `ingest_bytes()` 避免二次读取。默认上限 50MB。
- **XSS 防护**：`web_ui/chat.py` 引用卡片渲染前 `html.escape()` 转义文档内容。
- 中文分词：jieba 替换 LlamaIndex BM25 默认英文 tokenizer。所有 BM25 相关代码必须显式传入 `tokenizer=chinese_tokenizer`。
- 引用追踪：检索结果的 `node.metadata` 携带 `filename`、`page_number`、`heading_path`、`chunk_type`、`department_id` 等字段，前端引用卡片和 SSE citation 事件均从 metadata 提取——**不由 LLM 生成**。
- SSE 流式协议：`POST /api/chat/stream` 响应 `text/event-stream`，事件类型：`citation`(引用声明) → `token`(流式文本)×N → `done`(结束信号)。引擎未就绪返回 503。
- `QueryFusionRetriever`：必须显式传入 LLM 实例（DashScope），否则回退到全局 `Settings.llm`（默认 OpenAI），导致 `OPENAI_API_KEY` 检查失败。
- `DashScopeEmbedding`：`embed_batch_size=10`（DashScope API 单次上限 10 条，默认 25 会报 InvalidParameter）。
- `DashScope.astream_chat()`：返回 coroutine，需先 `await` 拿到 async generator 再 `async for` 迭代（新版 llama-index API 变更）。
- 异步方法（`aretrieve`/`arerank`）：用 `loop.run_in_executor` 包装同步调用，避免阻塞事件循环。
- 评估 LLM：`app/eval/metrics.py` 使用 DashScope OpenAI 兼容端点（`base_url` 指向 DashScope），通过 `openai.OpenAI` 客户端 + `ragas.llms.llm_factory` 创建，避免 `OPENAI_API_KEY` 环境变量泄漏。

## 当前开发阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| 一 | 环境奠基（pyproject.toml、config、FastAPI /health） | ✅ |
| 二 | ETL 链路（PDF/DOCX/MD/TXT 解析、表格感知切块、元数据注入、InMemoryDocStore） | ✅ |
| 三 | RAG 检索（BM25+Dense 混合检索 + RRF + bge-reranker + SSE 流式查询引擎） | ✅ |
| 四 | API 路由 + services + web_ui/ Streamlit 前端 | ✅ |
| 五 | Ragas 评估 + docs/ | ✅ |
| 六 | 安全加固（API Key 认证、速率限制、审计日志、XSS 防护、CORS 修复） | ✅ |

**测试**: 111 collected, 108 passed, 3 skipped（集成测试需 `RUN_RAG_TESTS=1` 或有效 `DASHSCOPE_API_KEY`）。

**总代码量**: 49 个 Python 文件（app 33 + web_ui 5 + scripts 2 + tests 12）。

## 模型与 API

- LLM: qwen-plus（通过 `llama-index-llms-dashscope`，依赖 `llama-index-llms-openai` 提供基类）
- Embedding: text-embedding-v3（通过 `llama-index-embeddings-dashscope`，batch size ≤10）
- API Key: `.env` 中 `DASHSCOPE_API_KEY`（需用户自行申请）；应用层 API Key 可选（`settings.api_key`）
- 重排序: bge-reranker-v2-m3（HuggingFace 本地加载，FlagEmbedding 不可用时自动降级为 pass-through）
- 评估 LLM: DashScope OpenAI 兼容端点（`https://dashscope.aliyuncs.com/compatible-mode/v1`）
- 安全: API Key 认证 + IP 速率限制 + 审计日志 + XSS 防护 + CORS 白名单

## 代码规范

- Python 3.12，uv 管理依赖，ruff 格式化（行宽 100）
- 所有 `__init__.py` 为空文件
- Pydantic v2 语法（`model_config`、`field_validator`），禁用 v1 风格
- 异步全链路：FastAPI async/await → SSE 流式响应，同步检索/重排方法通过 `run_in_executor` 桥接到异步调用

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
