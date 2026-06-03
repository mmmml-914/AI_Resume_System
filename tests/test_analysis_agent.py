"""AnalysisAgent 分析 Agent 单元测试"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from modules.analysis_agent import AnalysisAgent, ANALYSIS_TOOLS


class TestAnalysisAgentInit:
    """初始化测试"""

    def test_init(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        assert agent.name == "analysis"
        assert agent.llm is mock_llm

    def test_tool_definitions(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        tools = agent.get_tool_definitions()
        assert len(tools) == 3
        names = {t["function"]["name"] for t in tools}
        assert names == {"parse_resume", "knowledge_lookup", "polish_resume"}

    def test_tool_names(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        assert agent.get_tool_names() == {"parse_resume", "knowledge_lookup", "polish_resume"}


class TestAnalysisAgentToolDispatch:
    """工具派发测试"""

    def test_unknown_tool(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        result = agent.execute_tool("nonexistent")
        assert "error" in result

    def test_parse_resume_dispatches(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        agent._tool_parse_resume = MagicMock(return_value={"skills": ["Python"]})
        result = agent.execute_tool("parse_resume", resume_text="test")
        assert result["skills"] == ["Python"]

    def test_knowledge_lookup_dispatches(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        agent._tool_knowledge_lookup = MagicMock(return_value={"samples": [], "count": 0})
        result = agent.execute_tool("knowledge_lookup", category="ML", query_type="samples")
        assert result["count"] == 0

    def test_polish_dispatches(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        agent._tool_polish = MagicMock(return_value={"polished": "improved text"})
        result = agent.execute_tool("polish_resume", resume_text="test", category="ML")
        assert result["polished"] == "improved text"


class TestAnalysisToolParseResume:
    """_tool_parse_resume 测试"""

    def test_calls_extract(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_extract = MagicMock(return_value={"skills": ["Python"]})
        with patch.object(agent, '_get_module', return_value=mock_extract):
            result = agent._tool_parse_resume(resume_text="my resume")
            mock_extract.assert_called_once_with(
                "my resume",
                api_key=mock_llm.api_key,
                base_url=mock_llm.base_url,
            )
            assert result["skills"] == ["Python"]

    def test_wraps_string_result(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_extract = MagicMock(return_value="raw parsed text")
        with patch.object(agent, '_get_module', return_value=mock_extract):
            result = agent._tool_parse_resume(resume_text="test")
            assert result["parsed"] == "raw parsed text"


class TestAnalysisToolKnowledgeLookup:
    """_tool_knowledge_lookup 测试"""

    def test_samples(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        mock_kb.get_sample_resumes.return_value = ["sample1", "sample2", "sample3"]
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(category="ML", query_type="samples")
            assert result["count"] == 3
            mock_kb.get_sample_resumes.assert_called_once_with("ML", n=3)

    def test_stats(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        mock_kb.get_category_stats.return_value = {"ML": 50, "DS": 30}
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(category="ML", query_type="stats")
            assert result["ML"] == 50

    def test_excellent_avg(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        mock_kb.get_excellent_avg_scores.return_value = {"skills_match": 85}
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(category="ML", query_type="excellent_avg")
            assert result["avg_scores"]["skills_match"] == 85

    def test_comparison(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        mock_kb.compare_with_excellent.return_value = {"excellent_count": 3}
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(
                category="ML", query_type="comparison", resume_text="test"
            )
            assert result["excellent_count"] == 3

    def test_unknown_query_type(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(category="ML", query_type="invalid")
            assert "info" in result

    def test_no_comparison_data(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_kb = MagicMock()
        mock_kb.compare_with_excellent.return_value = None
        with patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_knowledge_lookup(
                category="ML", query_type="comparison", resume_text="test"
            )
            assert result["info"] == "无对比数据"


class TestAnalysisToolPolish:
    """_tool_polish 测试"""

    def test_polish_calls_polisher(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_polisher = MagicMock()
        mock_polisher.polish.return_value = {"polished": "new text"}
        with patch.object(agent, '_get_module', return_value=mock_polisher):
            result = agent._tool_polish(resume_text="old text", category="ML", focus="quantify")
            mock_polisher.polish.assert_called_once_with("old text", "ML", "quantify")
            assert result["polished"] == "new text"

    def test_polish_empty_focus(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        mock_polisher = MagicMock()
        with patch.object(agent, '_get_module', return_value=mock_polisher):
            agent._tool_polish(resume_text="text", category="ML", focus="")
            mock_polisher.polish.assert_called_once_with("text", "ML", "")


class TestAnalysisAgentErrorHandling:
    """错误处理"""

    def test_tool_exception_formatted(self, mock_llm):
        agent = AnalysisAgent(mock_llm)
        agent._tool_parse_resume = MagicMock(side_effect=ValueError("parse failed"))
        result = agent.execute_tool("parse_resume", resume_text="test")
        assert "error" in result
        assert result["error_type"] == "ValueError"
        assert result["error_context"] == "analysis:parse_resume"
