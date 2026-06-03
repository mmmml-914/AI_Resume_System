"""AgentCoordinator 核心路由与 Pipeline 测试"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from modules.coordinator import AgentCoordinator
from modules.agent_base import WorkflowState, WorkflowStep


class TestCoordinatorPreRoute:
    """关键词预检路由（Level 1，零成本、零延迟）"""

    def test_pre_route_analysis_chinese(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("帮我解析这份简历") == "analysis"
        assert c._pre_route("查一下知识库的统计数据") == "analysis"
        assert c._pre_route("润色这段文字") == "analysis"

    def test_pre_route_analysis_english(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("parse this resume") == "analysis"
        assert c._pre_route("show me knowledge samples") == "analysis"
        assert c._pre_route("polish my resume") == "analysis"

    def test_pre_route_evaluation_chinese(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        # "评分" → evaluation:1
        assert c._pre_route("帮我评分这个简历") == "evaluation"
        # "评一下" → evaluation:1
        assert c._pre_route("评一下这份简历的质量") == "evaluation"
        # "评价" → evaluation:1
        assert c._pre_route("评价一下这个简历") == "evaluation"

    def test_pre_route_evaluation_english(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("evaluate this resume") == "evaluation"
        assert c._pre_route("score my resume") == "evaluation"

    def test_pre_route_interview_chinese(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("我想开始面试") == "interview"
        assert c._pre_route("模拟面试准备") == "interview"

    def test_pre_route_interview_english(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("start interview") == "interview"

    def test_pre_route_no_match(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._pre_route("你好") is None
        assert c._pre_route("今天天气不错") is None
        assert c._pre_route("") is None

    def test_pre_route_multiple_keywords(self, mock_llm):
        """多个关键词命中时取匹配数最多的"""
        c = AgentCoordinator(mock_llm)
        # "评分" (evaluation:1) vs "润色" (analysis:1) — 先比较 scores
        result = c._pre_route("评分和润色哪个更好")
        # evaluation 有 "评分" 命中，analysis 有 "润色" 命中，score 相同
        # 最早 max 按 dict 插入顺序 return 第一个
        assert result in ("analysis", "evaluation")


class TestCoordinatorLLMRoute:
    """LLM 函数调用路由（Level 2）"""

    def test_route_llm_returns_analysis(self, mock_llm_with_tools):
        """LLM 返回 route_to_analysis"""
        c = AgentCoordinator(mock_llm_with_tools("route_to_analysis"))
        route = c._route("帮我看看这个简历内容")
        assert route == "analysis"

    def test_route_llm_returns_evaluation(self, mock_llm_with_tools):
        c = AgentCoordinator(mock_llm_with_tools("route_to_evaluation"))
        route = c._route("评估下这份简历")
        assert route == "evaluation"

    def test_route_llm_returns_interview(self, mock_llm_with_tools):
        c = AgentCoordinator(mock_llm_with_tools("route_to_interview"))
        route = c._route("开始面试")
        assert route == "interview"

    def test_route_llm_fallback_to_confirm(self, mock_llm):
        """LLM 无 tool_calls → 返回 confirm"""
        c = AgentCoordinator(mock_llm)
        route = c._route("随便聊聊")
        assert route == "confirm"


class TestCoordinatorGetAgent:
    """Agent 获取测试"""

    def test_get_analysis_agent(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._get_agent("analysis") is c.analysis_agent

    def test_get_evaluation_agent(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._get_agent("evaluation") is c.evaluation_agent

    def test_get_interview_agent(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._get_agent("interview") is c.interview_agent

    def test_get_agent_unknown(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._get_agent("unknown") is None


class TestCoordinatorExecuteTool:
    """工具派发测试"""

    def test_execute_tool_routes_correctly(self, mock_llm):
        c = AgentCoordinator(mock_llm)

        # Mock 底层 tool 方法直接返回结果
        c.analysis_agent.execute_tool = MagicMock(return_value={"ok": "analysis"})
        c.evaluation_agent.execute_tool = MagicMock(return_value={"ok": "evaluation"})

        assert c.execute_tool("parse_resume", resume_text="test") == {"ok": "analysis"}
        c.analysis_agent.execute_tool.assert_called_once_with("parse_resume", resume_text="test")

    def test_execute_tool_evaluation(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        c.evaluation_agent.execute_tool = MagicMock(return_value={"ok": "eval"})
        assert c.execute_tool("evaluate_resume", resume_text="test", category="ML") == {"ok": "eval"}
        c.evaluation_agent.execute_tool.assert_called_once_with("evaluate_resume", resume_text="test", category="ML")

    def test_execute_tool_unknown(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        result = c.execute_tool("nonexistent_tool")
        assert "error" in result

    def test_execute_tool_error_formatting(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        c.analysis_agent.execute_tool = MagicMock(side_effect=ValueError("bad stuff"))
        result = c.execute_tool("parse_resume")
        assert "error" in result
        assert result["error_type"] == "ValueError"
        assert result["error_context"] == "tool:parse_resume"


class TestCoordinatorToolRegistry:
    """工具注册表完整性"""

    def test_all_tools_registered(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        # 总共 8 个工具
        expected_tools = [
            "parse_resume", "knowledge_lookup", "polish_resume",
            "evaluate_resume", "collect_resume",
            "start_interview", "interview_chat", "end_interview",
        ]
        assert set(c._tool_registry.keys()) == set(expected_tools)

    def test_tool_registry_ownership(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c._tool_registry["parse_resume"] is c.analysis_agent
        assert c._tool_registry["evaluate_resume"] is c.evaluation_agent
        assert c._tool_registry["start_interview"] is c.interview_agent

    def test_get_tool_definitions_returns_all(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        all_tools = c.get_tool_definitions()
        names = {t["function"]["name"] for t in all_tools}
        assert len(names) == 8


class TestCoordinatorProcessUserRequest:
    """process_user_request 综合路由测试"""

    def test_keyword_analysis_routing(self, mock_llm):
        """解析简历 → 路由到 analysis_agent.process"""
        c = AgentCoordinator(mock_llm)
        c.analysis_agent.process = MagicMock(return_value={"type": "text", "content": "done"})
        result = c.process_user_request("帮我解析一下这份简历")
        c.analysis_agent.process.assert_called_once()
        assert result["content"] == "done"

    def test_keyword_evaluation_routing(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        c.evaluation_agent.process = MagicMock(return_value={"type": "text", "content": "scored"})
        result = c.process_user_request("帮我评分这份简历")
        c.evaluation_agent.process.assert_called_once()
        assert result["content"] == "scored"

    def test_confirm_message(self, mock_llm):
        """无法确定意图 → 返回确认消息"""
        c = AgentCoordinator(mock_llm)
        result = c.process_user_request("你好")
        assert result["type"] == "text"
        # 确认消息应包含选项引导
        content = result["content"]
        assert "解析" in content or "评估" in content or "面试" in content

    def test_unknown_agent_fallback(self, mock_llm):
        """_get_agent 返回 None → 错误提示"""
        c = AgentCoordinator(mock_llm)
        with patch.object(c, '_route', return_value="nonexistent"):
            result = c.process_user_request("你好")
            assert "无法路由" in result["content"]


class TestCoordinatorPipelineFullEval:
    """pipeline_full_evaluation 全流程测试"""

    def test_success_path(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)

        # Mock 具体的工具方法
        c.analysis_agent._tool_parse_resume = MagicMock(return_value={
            "skills": ["Python", "ML"], "education": "Master"
        })
        c.analysis_agent._tool_knowledge_lookup = MagicMock(return_value={
            "samples": ["sample1", "sample2"], "count": 2
        })
        c.evaluation_agent._tool_evaluate = MagicMock(return_value={
            "overall": 80, "dimensions": [], "strengths": [], "weaknesses": [],
            "suggestions": [], "summary": "Good",
        })

        result = c.pipeline_full_evaluation(sample_resume_text, "Data Science")
        assert result["workflow_status"] == "completed"
        assert result["overall"] == 80
        assert result["structured_resume"]["skills"] == ["Python", "ML"]

    def test_parse_failure(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)
        # execute_tool 抛出异常 → pipeline 的 except 分支拦截
        c.analysis_agent.execute_tool = MagicMock(side_effect=RuntimeError("Parse failed"))

        result = c.pipeline_full_evaluation(sample_resume_text, "Data Science")
        assert result["workflow_status"] == "failed"
        assert "error" in result

    def test_state_tracking(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)
        c.analysis_agent._tool_parse_resume = MagicMock(return_value={"skills": ["Python"]})
        c.analysis_agent._tool_knowledge_lookup = MagicMock(return_value={"samples": [], "count": 0})
        c.evaluation_agent._tool_evaluate = MagicMock(return_value={"overall": 75, "dimensions": [],
            "strengths": [], "weaknesses": [], "suggestions": [], "summary": ""})

        c.pipeline_full_evaluation(sample_resume_text, "Data Science")
        assert c.state.workflow_name == "full_evaluation"
        assert c.state.status == "completed"
        assert len(c.state.steps) == 3
        for step in c.state.steps:
            assert step.status == "completed"

    def test_accumulated_data(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)
        c.analysis_agent._tool_parse_resume = MagicMock(return_value={"skills": ["Python"]})
        c.analysis_agent._tool_knowledge_lookup = MagicMock(return_value={"samples": [], "count": 0})
        c.evaluation_agent._tool_evaluate = MagicMock(return_value={"overall": 75, "dimensions": [],
            "strengths": [], "weaknesses": [], "suggestions": [], "summary": ""})

        c.pipeline_full_evaluation(sample_resume_text, "Data Science")
        assert "parse_resume" in c.state.accumulated_data
        assert "knowledge_samples" in c.state.accumulated_data
        assert "evaluate_resume" in c.state.accumulated_data


class TestCoordinatorPipelinePolish:
    """pipeline_polish_and_evaluate 测试"""

    def test_success_path(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)

        polish_result = {
            "polished": "Improved resume text",
            "changes": [{"original": "old", "improved": "new", "reason": "better"}],
            "keywords_added": ["Python", "ML"],
            "suggestions": ["Add more metrics"],
        }
        eval_before = {"overall": 70, "dimensions": [
            {"key": "skills_match", "label": "技能匹配度", "score": 70, "weight": 0.3},
            {"key": "project_quality", "label": "项目经验质量", "score": 70, "weight": 0.25},
            {"key": "format_readability", "label": "格式与可读性", "score": 70, "weight": 0.15},
            {"key": "education", "label": "教育背景", "score": 70, "weight": 0.15},
            {"key": "expression", "label": "内容表达", "score": 70, "weight": 0.15},
        ], "strengths": [], "weaknesses": [],
           "suggestions": [], "summary": ""}
        eval_after = {**eval_before, "overall": 80,
                      "dimensions": [{**d, "score": 80} for d in eval_before["dimensions"]]}

        c.evaluation_agent._tool_evaluate = MagicMock(side_effect=[eval_before, eval_after])
        c.analysis_agent._tool_polish = MagicMock(return_value=polish_result)

        result = c.pipeline_polish_and_evaluate(sample_resume_text, "Data Science")
        assert result["workflow_status"] == "completed"
        assert result["overall_before"] == 70
        assert result["overall_after"] == 80
        assert result["overall_delta"] == 10
        assert "polished_text" in result
        assert result["polished_text"] == "Improved resume text"

    def test_delta_calculation(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)
        eval_before = {"overall": 70, "dimensions": [
            {"key": "skills_match", "label": "技能匹配度", "score": 70},
            {"key": "project_quality", "label": "项目经验质量", "score": 70},
            {"key": "format_readability", "label": "格式与可读性", "score": 70},
            {"key": "education", "label": "教育背景", "score": 70},
            {"key": "expression", "label": "内容表达", "score": 70},
        ], "strengths": [], "weaknesses": [], "suggestions": [], "summary": ""}
        eval_after = {"overall": 85, "dimensions": [
            {"key": "skills_match", "label": "技能匹配度", "score": 90},
            {"key": "project_quality", "label": "项目经验质量", "score": 85},
            {"key": "format_readability", "label": "格式与可读性", "score": 80},
            {"key": "education", "label": "教育背景", "score": 85},
            {"key": "expression", "label": "内容表达", "score": 80},
        ], "strengths": [], "weaknesses": [], "suggestions": [], "summary": ""}

        c.evaluation_agent._tool_evaluate = MagicMock(side_effect=[eval_before, eval_after])
        c.analysis_agent._tool_polish = MagicMock(return_value={
            "polished": "new text", "changes": [], "keywords_added": [], "suggestions": []
        })

        result = c.pipeline_polish_and_evaluate(sample_resume_text, "Data Science")
        assert result["score_deltas"]["skills_match"]["delta"] == 20
        assert result["score_deltas"]["project_quality"]["delta"] == 15


class TestCoordinatorStateManagement:
    """状态管理测试"""

    def test_get_state(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert isinstance(c.get_state(), WorkflowState)
        assert c.get_state().status == "idle"

    def test_reset_state(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        c.state.status = "completed"
        c.state.workflow_name = "test"
        c.reset_state()
        assert c.get_state().status == "idle"
        assert c.get_state().workflow_name == ""

    def test_get_step_result(self, mock_llm, sample_resume_text):
        c = AgentCoordinator(mock_llm)
        c.analysis_agent._tool_parse_resume = MagicMock(return_value={"skills": ["Python"]})
        c.analysis_agent._tool_knowledge_lookup = MagicMock(return_value={"samples": [], "count": 0})
        c.evaluation_agent._tool_evaluate = MagicMock(return_value={"overall": 75, "dimensions": [],
            "strengths": [], "weaknesses": [], "suggestions": [], "summary": ""})
        c.pipeline_full_evaluation(sample_resume_text, "ML")
        step_result = c.get_step_result("parse_resume")
        assert step_result == {"skills": ["Python"]}

    def test_get_step_result_none(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c.get_step_result("nonexistent") is None


class TestCoordinatorLlmProperty:
    """llm 属性暴露"""

    def test_llm_property(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c.llm is mock_llm

    def test_llm_passed_to_agents(self, mock_llm):
        c = AgentCoordinator(mock_llm)
        assert c.analysis_agent.llm is mock_llm
        assert c.evaluation_agent.llm is mock_llm
        assert c.interview_agent.llm is mock_llm
