"""评估模块测试 — 覆盖 dataset / report / runner 核心逻辑。

集成测试（需要 DASHSCOPE_API_KEY）标记为 skip，
通过 RUN_RAG_TESTS=1 手动触发。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval.dataset import QASample, load_qa_dataset
from app.eval.report import EvalReport

# ── Dataset ────────────────────────────────────────────────

class TestQASample:
    """QASample 数据类单元测试。"""

    def test_from_dict_valid(self):
        sample = QASample.from_dict({
            "user_input": "什么是RAG？",
            "reference": "RAG是检索增强生成。",
            "reference_contexts": ["ctx1", "ctx2"],
            "source_document": "doc.md",
        })
        assert sample.user_input == "什么是RAG？"
        assert sample.reference == "RAG是检索增强生成。"
        assert len(sample.reference_contexts) == 2
        assert sample.source_document == "doc.md"

    def test_from_dict_minimal(self):
        """仅有必填字段应正常构造。"""
        sample = QASample.from_dict({
            "user_input": "问题",
            "reference": "答案",
        })
        assert sample.reference_contexts == []
        assert sample.source_document == ""
        assert sample.response == ""
        assert sample.retrieved_contexts == []

    def test_from_dict_missing_user_input(self):
        with pytest.raises(ValueError, match="user_input"):
            QASample.from_dict({"user_input": "", "reference": "x"})

    def test_from_dict_missing_reference(self):
        with pytest.raises(ValueError, match="reference"):
            QASample.from_dict({"user_input": "q", "reference": ""})

    def test_from_dict_strips_whitespace(self):
        sample = QASample.from_dict({
            "user_input": "  什么是RAG？  ",
            "reference": "  答案  ",
        })
        assert sample.user_input == "什么是RAG？"
        assert sample.reference == "答案"


class TestLoadQADataset:
    """load_qa_dataset 函数测试。"""

    def test_load_valid_file(self, tmp_path: Path):
        data = [
            {"user_input": "Q1", "reference": "A1"},
            {"user_input": "Q2", "reference": "A2", "reference_contexts": ["c"]},
        ]
        json_path = tmp_path / "qa.json"
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        samples = load_qa_dataset(json_path)
        assert len(samples) == 2
        assert samples[0].user_input == "Q1"
        assert samples[1].reference_contexts == ["c"]

    def test_load_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="不存在"):
            load_qa_dataset(tmp_path / "nonexistent.json")

    def test_load_invalid_json(self, tmp_path: Path):
        json_path = tmp_path / "invalid.json"
        json_path.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON 解析"):
            load_qa_dataset(json_path)

    def test_load_not_array(self, tmp_path: Path):
        json_path = tmp_path / "obj.json"
        json_path.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(ValueError, match="数组"):
            load_qa_dataset(json_path)

    def test_load_invalid_sample(self, tmp_path: Path):
        data = [{"user_input": "Q1", "reference": "A1"}, {"no_input": "x"}]
        json_path = tmp_path / "bad.json"
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError, match="第 1 条"):
            load_qa_dataset(json_path)


# ── Report ─────────────────────────────────────────────────

class TestEvalReport:
    """EvalReport 报告生成测试。"""

    def test_default_values(self):
        report = EvalReport()
        assert report.total_queries == 0
        assert report.avg_latency_ms == 0.0
        assert report.metrics == {}
        assert report.individual_scores == []
        assert report.timestamp  # auto-generated

    def test_to_json_string(self):
        report = EvalReport(
            metrics={"faithfulness": 0.95, "context_recall": 0.80},
            individual_scores=[{"user_input": "Q1"}],
            total_queries=1,
            avg_latency_ms=150.0,
        )
        output = report.to_json()
        assert isinstance(output, str)
        parsed = json.loads(output)
        assert parsed["metrics"]["faithfulness"] == 0.95
        assert parsed["total_queries"] == 1

    def test_to_json_file(self, tmp_path: Path):
        report = EvalReport(metrics={"faithfulness": 0.9}, total_queries=2)
        out_path = tmp_path / "report.json"
        report.to_json(out_path)
        assert out_path.exists()
        content = json.loads(out_path.read_text(encoding="utf-8"))
        assert content["metrics"]["faithfulness"] == 0.9

    def test_to_console_format(self):
        report = EvalReport(
            metrics={"faithfulness": 1.0, "context_recall": 0.5},
            individual_scores=[
                {"user_input": "Q1", "response": "A1", "reference": "R1"},
            ],
            total_queries=1,
        )
        output = report.to_console()
        assert "RAG" in output
        assert "faithfulness" in output or "忠实度" in output
        assert "Q1" in output

    def test_to_console_empty_metrics(self):
        report = EvalReport(total_queries=0)
        output = report.to_console()
        assert "(无指标数据)" in output or "无指标" in output


# ── CLI Mock ───────────────────────────────────────────────

class TestCLIMockMode:
    """Mock 模式 Smoke 测试 — 不依赖 API key。"""

    def test_mock_mode_imports(self):
        """验证 mock 模式所需的所有导入可用。"""
        from ragas import EvaluationDataset, SingleTurnSample

        sample = SingleTurnSample(
            user_input="test?",
            response="response",
            retrieved_contexts=["ctx"],
            reference="ref",
        )
        dataset = EvaluationDataset([sample])
        assert len(dataset) == 1

    def test_dataset_construction(self):
        """验证 EvaluationDataset 可正常构造。"""
        from ragas import EvaluationDataset, SingleTurnSample

        samples = [
            SingleTurnSample(
                user_input="Q1",
                response="A1",
                retrieved_contexts=["ctx1"],
                reference="R1",
            ),
            SingleTurnSample(
                user_input="Q2",
                response="A2",
                retrieved_contexts=["ctx2"],
                reference="R2",
                reference_contexts=["ref_ctx"],
            ),
        ]
        dataset = EvaluationDataset(samples)
        assert len(dataset) == 2


# ── Integration ────────────────────────────────────────────

@pytest.mark.skip(
    reason="需要有效的 DASHSCOPE_API_KEY 和文档入库，设置 RUN_RAG_TESTS=1 手动运行"
)
class TestEvalIntegration:
    """端到端评估集成测试 — 需要 API key 和真实 LLM 调用。"""

    @pytest.mark.asyncio
    async def test_full_evaluation_pipeline(self, tmp_path: Path):
        """完整评估流程：入库 → 检索 → 生成 → Ragas 评分。"""
        from app.eval.dataset import load_qa_dataset
        from app.eval.metrics import get_ragas_metrics
        from app.eval.runner import EvalRunner

        # 使用独立持久化目录
        runner = EvalRunner(persist_dir=str(tmp_path / "eval_store"))

        # 入库评估文档
        docs = list(Path("data/eval").glob("*.md"))
        if docs:
            ingested = runner.ingest_eval_docs([str(d) for d in docs])
            assert len(ingested) > 0

        # 加载数据集
        samples = load_qa_dataset("data/eval/qa_pairs.json")

        # 取前 2 条做快速冒烟
        metrics = get_ragas_metrics()
        report = await runner.run_evaluation(samples[:2], metrics=metrics)

        assert report.total_queries == 2
        assert len(report.metrics) > 0
        # 验证所有指标值在 [0, 1] 范围内
        for name, value in report.metrics.items():
            assert 0.0 <= value <= 1.0, f"{name}={value} out of range"


# ── EvalRunner Unit ────────────────────────────────────────

class TestEvalRunnerUnit:
    """EvalRunner 单元测试（mock API 调用）。"""

    def test_init_default_persist_dir(self):
        from app.eval.runner import EvalRunner
        runner = EvalRunner()
        assert runner._store is not None
        assert runner._pipeline is not None
        assert runner._query_service is None  # 延迟初始化

    def test_init_custom_persist_dir(self, tmp_path: Path):
        from app.eval.runner import EvalRunner
        runner = EvalRunner(persist_dir=str(tmp_path / "eval"))
        assert "eval" in runner._persist_dir

    def test_ingest_nonexistent_file(self):
        from app.eval.runner import EvalRunner
        runner = EvalRunner()
        result = runner.ingest_eval_docs(["nonexistent_file.md"])
        assert result == []  # 不存在的文件静默跳过

    def test_ingest_valid_markdown(self, tmp_path: Path):
        from app.eval.runner import EvalRunner
        md_path = tmp_path / "test.md"
        md_path.write_text("# 标题\n\n这是测试内容。", encoding="utf-8")

        runner = EvalRunner(persist_dir=str(tmp_path / "store"))
        result = runner.ingest_eval_docs([str(md_path)])
        assert len(result) == 1
        assert "test.md" in result

    @pytest.mark.asyncio
    async def test_run_query_engine_not_ready(self):
        from app.eval.runner import EvalRunner
        runner = EvalRunner()
        result = await runner.run_query("测试问题")
        assert result.error == "RAG engine not ready"
        assert result.response == ""
