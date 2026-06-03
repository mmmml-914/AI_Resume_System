"""EvaluationAgent 评估 Agent 单元测试"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from modules.evaluation_agent import EvaluationAgent, EVALUATION_TOOLS


class TestEvaluationAgentInit:
    """初始化测试"""

    def test_init(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        assert agent.name == "evaluation"
        assert agent.llm is mock_llm

    def test_tool_definitions(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        tools = agent.get_tool_definitions()
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"evaluate_resume", "collect_resume"}

    def test_tool_names(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        assert agent.get_tool_names() == {"evaluate_resume", "collect_resume"}


class TestEvaluationAgentToolDispatch:
    """工具派发测试"""

    def test_unknown_tool(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        result = agent.execute_tool("nonexistent")
        assert "error" in result

    def test_evaluate_dispatches(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        agent._tool_evaluate = MagicMock(return_value={"overall": 85})
        result = agent.execute_tool("evaluate_resume", resume_text="test", category="ML")
        assert result["overall"] == 85

    def test_collect_dispatches(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        agent._tool_collect = MagicMock(return_value={"success": True, "id": "abc123"})
        result = agent.execute_tool(
            "collect_resume", category="ML", title="Test",
            source="web", resume_text="resume text"
        )
        assert result["success"] is True


class TestEvaluationToolEvaluate:
    """_tool_evaluate 测试"""

    def test_calls_evaluator(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = {"overall": 82, "dimensions": []}
        with patch.object(agent, '_get_module', return_value=mock_evaluator):
            result = agent._tool_evaluate(resume_text="my resume", category="Data Science")
            mock_evaluator.evaluate.assert_called_once_with(
                "my resume", "Data Science", n_samples=1
            )
            assert result["overall"] == 82

    def test_evaluate_with_n_samples(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        mock_evaluator = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_evaluator):
            agent._tool_evaluate(resume_text="test", category="ML", n_samples=3)
            mock_evaluator.evaluate.assert_called_once_with("test", "ML", n_samples=3)


class TestEvaluationToolCollect:
    """_tool_collect 测试"""

    def test_collect_adds_to_collector(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        mock_collector = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_collector):
            result = agent._tool_collect(
                category="Data Science",
                title="211硕-字节offer",
                source="牛客网",
                resume_text="Skills: Python, SQL. Improved CTR by 15%",
                background="211硕士",
            )
            assert result["success"] is True
            # 验证传给 collector 的数据
            added_entry = mock_collector.add.call_args[0][0]
            assert added_entry["category"] == "Data Science"
            assert added_entry["title"] == "211硕-字节offer"
            assert added_entry["source"] == "牛客网"
            assert added_entry["background"] == "211硕士"
            assert added_entry["features"]["quantification"] is True  # contains "15%"

    def test_collect_minimal(self, mock_llm):
        """只传必需参数"""
        agent = EvaluationAgent(mock_llm)
        mock_collector = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_collector):
            result = agent._tool_collect(
                category="ML",
                title="ML工程师简历",
                source="知乎",
                resume_text="Python PyTorch",
            )
            assert result["success"] is True
            added = mock_collector.add.call_args[0][0]
            assert added["background"] == ""
            assert added["features"]["quantification"] is False

    def test_collect_generates_id(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        mock_collector = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_collector):
            result = agent._tool_collect(
                category="DS", title="T", source="S", resume_text="text"
            )
            assert "agent_" in result["id"]


class TestEvaluationAgentErrorHandling:
    """错误处理测试"""

    def test_tool_exception_formatted(self, mock_llm):
        agent = EvaluationAgent(mock_llm)
        agent._tool_evaluate = MagicMock(side_effect=RuntimeError("evaluator crash"))
        result = agent.execute_tool("evaluate_resume", resume_text="test", category="ML")
        assert "error" in result
        assert result["error_context"] == "evaluation:evaluate_resume"
