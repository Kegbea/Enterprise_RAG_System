# 评估指南

## 概述

系统使用 [Ragas](https://docs.ragas.io/) 评估 RAG 管道的检索和生成质量。
评估模块位于 [app/eval/](../app/eval/)，评估数据存放在 [data/eval/](../data/eval/)。

## 评估指标

| 指标 | 英文名 | 评估对象 | 说明 |
|------|--------|----------|------|
| 上下文精确率 | `context_precision` | 检索 | 检索到的上下文中有多少与参考答案相关 |
| 上下文召回率 | `context_recall` | 检索 | 参考答案中有多少能从检索上下文找到 |
| 忠实度 | `faithfulness` | 生成 | 回答是否完全基于检索上下文（无幻觉） |
| 回答相关性 | `answer_relevancy` | 生成 | 回答与问题的相关程度 |
| 回答正确性 | `answer_correctness` | 生成 | 回答与参考答案的一致性 |

所有指标值范围 [0, 1]，越高越好。

## 运行评估

### Mock 模式（推荐初次验证）

不调用 LLM API，使用占位数据验证评估流程：

```bash
uv run python -m app.eval.cli --mock
```

### 完整评估

需要配置 `DASHSCOPE_API_KEY`：

```bash
# 使用默认数据集
uv run python -m app.eval.cli

# 指定数据集和输出
uv run python -m app.eval.cli \
  --dataset data/eval/qa_pairs.json \
  --doc-dir data/eval \
  --output data/eval/report.json

# 详细日志
uv run python -m app.eval.cli -v
```

### 编程方式

```python
from app.eval.dataset import load_qa_dataset
from app.eval.metrics import get_ragas_metrics
from app.eval.runner import EvalRunner

runner = EvalRunner()

# 入库评估文档
runner.ingest_eval_docs(["data/eval/sample_knowledge.md"])

# 运行评估
samples = load_qa_dataset("data/eval/qa_pairs.json")
metrics = get_ragas_metrics()
report = await runner.run_evaluation(samples, metrics=metrics)

# 输出
print(report.to_console())
report.to_json("report.json")
```

## 数据集格式

评估数据集为 JSON 数组，每条样本包含：

```json
{
  "user_input": "什么是 RAG？",
  "reference": "RAG 是检索增强生成技术...",
  "reference_contexts": [
    "RAG 结合了检索和生成...",
    "RAG 有三大优势..."
  ],
  "source_document": "sample_knowledge.md"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_input` | string | 是 | 评估用查询问题 |
| `reference` | string | 是 | 参考答案（ground truth） |
| `reference_contexts` | string[] | 否 | 参考上下文片段列表（用于检索指标） |
| `source_document` | string | 否 | 关联的知识文档文件名 |

### 数据集准备建议

1. **覆盖多种问题类型**：事实查询、推理综合、表格数据、否定问题
2. **每条样本 20 条以上**可获得统计意义的评估结果
3. **参考上下文**应尽量对应实际文档片段，避免太宽泛
4. **参考答安**应具体明确，给评估 LLM 提供清晰的比较基准
5. 从实际用户问题中采样效果最佳

## 结果解读

### 检索质量

- `context_precision` < 0.5：检索到的上下文噪声多，考虑调整 chunk_size 或提升重排序
- `context_recall` < 0.5：相关信息未被检索到，考虑扩大 top_k 或优化 embedding

### 生成质量

- `faithfulness` < 0.7：LLM 有编造倾向，检查 system prompt 或降低 temperature
- `answer_relevancy` < 0.7：回答偏题，考虑优化上下文拼接格式
- `answer_correctness` < 0.7：回答与参考答案偏差大，可能需要更精准的检索

## 自定义评估

### 自定义 LLM

评估 LLM 默认使用 qwen-plus（DashScope 兼容端点）。如需更换：

```python
from app.eval.metrics import get_evaluator_llm

llm = get_evaluator_llm()
# 修改 llm 参数...
```

### 自定义指标

```python
from ragas.metrics import faithfulness
from app.eval.metrics import get_evaluator_llm

faithfulness.llm = get_evaluator_llm()
# 仅使用部分指标
metrics = [faithfulness]
```

## 集成测试

评估相关的集成测试标记为 skip，通过环境变量手动触发：

```bash
# 需要 DASHSCOPE_API_KEY
RUN_RAG_TESTS=1 uv run pytest tests/test_eval.py::TestEvalIntegration -v
```
