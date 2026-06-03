"""InterviewAgent & InterviewSession 单元测试"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from modules.interview_agent import (
    InterviewAgent, InterviewSession,
    INTERVIEW_TOOLS, INTERVIEWER_SYSTEM_PROMPT, REPORT_SYSTEM_PROMPT,
)


# ======================================================================
# InterviewSession 测试
# ======================================================================

class TestInterviewSessionInit:
    """面试会话初始化"""

    def test_init(self, mock_llm, sample_resume_text, sample_evaluation_report):
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        assert session.resume_text == sample_resume_text
        assert session.evaluation == sample_evaluation_report
        assert session.messages == []

    def test_init_without_llm_client(self, sample_resume_text, sample_evaluation_report):
        """不传 llm_client 时使用默认 OpenAI 客户端"""
        with patch("modules.interview_agent.OpenAI") as mock_openai:
            session = InterviewSession(sample_resume_text, sample_evaluation_report)
            assert session.resume_text == sample_resume_text


class TestInterviewSessionBuildPrompt:
    """个性化提示词构建"""

    def test_build_prompt_identifies_weak_areas(self, sample_resume_text):
        report = {
            "dimensions": [
                {"key": "skills_match", "label": "技能匹配度", "score": 45},
                {"key": "project_quality", "label": "项目经验质量", "score": 85},
                {"key": "format_readability", "label": "格式与可读性", "score": 60},
            ],
            "weaknesses": ["项目描述缺乏技术深度"],
        }
        session = InterviewSession(sample_resume_text, report)
        prompt = session._build_personalized_prompt()
        # 弱项应该被提及
        assert "技能匹配度(45分)" in prompt
        assert "格式与可读性(60分)" in prompt
        # 强项也应该被提及
        assert "项目经验质量(85分)" in prompt
        # weaknesses 应该出现
        assert "项目描述缺乏技术深度" in prompt

    def test_build_prompt_no_weaknesses(self, sample_resume_text):
        report = {
            "dimensions": [
                {"key": "skills_match", "label": "技能匹配度", "score": 90},
            ],
        }
        session = InterviewSession(sample_resume_text, report)
        prompt = session._build_personalized_prompt()
        # "个性化面试重点" 段落不应包含弱项（因为所有维度都是强项）
        assert "技能匹配度(90分)" in prompt
        # 弱项为空 → 应跳过"请重点考察"这段弱项描述
        assert "请重点考察" not in prompt

    def test_build_prompt_with_excellent_comparison(self, sample_resume_text):
        """与优秀简历对比数据应被注入"""
        report = {
            "dimensions": [
                {"key": "skills_match", "label": "技能匹配度", "score": 70},
            ],
            "excellent_comparison": {
                "avg_scores": {"skills_match": 90},
            },
        }
        session = InterviewSession(sample_resume_text, report)
        # _build_personalized_prompt 本身不包含 comparison，
        # comparison 在 start() 中拼接到 user_content
        # 这里只验证不报错
        prompt = session._build_personalized_prompt()
        assert prompt is not None


class TestInterviewSessionChat:
    """面试对话测试"""

    def test_start_calls_llm(self, mock_llm, sample_resume_text, sample_evaluation_report):
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        # Mock _call_llm 返回固定响应
        session._call_llm = MagicMock(return_value="欢迎参加面试，请先介绍一下你的项目经验。")
        reply = session.start()
        assert reply == "欢迎参加面试，请先介绍一下你的项目经验。"
        # start() 构建 [system, user] → _call_llm → append assistant → 共 3 条
        assert len(session.messages) == 3

    def test_chat_appends_messages(self, mock_llm, sample_resume_text, sample_evaluation_report):
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        session._call_llm = MagicMock(return_value="mock reply")
        session.start()
        session._call_llm = MagicMock(return_value="很好的回答，那请谈谈你的第二个项目。")
        reply = session.chat("我做过一个NLP项目")
        assert reply == "很好的回答，那请谈谈你的第二个项目。"
        # start() → [system, user, assistant] = 3, chat() → [+ user, + assistant] = 5
        assert len(session.messages) == 5

    def test_chat_stream(self, mock_llm, sample_resume_text, sample_evaluation_report):
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        # Mock 流式方法
        def fake_stream():
            for token in ["继续", "提问", "..."]:
                yield token
        session._call_llm_stream = MagicMock(return_value=fake_stream())

        session._call_llm = MagicMock(return_value="warmup")
        session.start()

        tokens = list(session.chat_stream("我的回答是..."))
        assert len(tokens) == 3
        assert "".join(tokens) == "继续提问..."
        # 消息应被记录到历史
        assert session.messages[-1]["role"] == "assistant"
        assert session.messages[-1]["content"] == "继续提问..."


class TestInterviewSessionEnd:
    """结束面试 & 报告生成"""

    def test_end_interview(self, mock_llm, sample_resume_text, sample_evaluation_report):
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        session._call_llm = MagicMock(return_value="欢迎参加面试")
        session.start()

        # end_interview 直接调用 client.chat.completions.create 而非 _call_llm
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = (
            '{"overall": 75, "dimensions": {}, "strengths": ["沟通清晰"], '
            '"weaknesses": [], "suggestions": ["多练"]}'
        )
        session.client.chat.completions.create.return_value = mock_resp

        report = session.end_interview()
        assert report["overall"] == 75
        assert "stats" in report
        assert report["stats"]["total_questions"] >= 0

    def test_end_interview_json_fallback(self, mock_llm, sample_resume_text, sample_evaluation_report):
        """LLM 返回 markdown 包裹的 JSON 时也能正确解析"""
        session = InterviewSession(sample_resume_text, sample_evaluation_report, llm_client=mock_llm)
        session._call_llm = MagicMock(return_value="欢迎")
        session.start()

        # 返回 markdown 包裹的 JSON
        md_json = '```json\n{"overall": 72, "dimensions": {"technical_accuracy": {"score": 68, "comment": "需提升"}}, "strengths": [], "weaknesses": [], "suggestions": []}\n```'
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = md_json
        session.client.chat.completions.create.return_value = mock_resp

        report = session.end_interview()
        assert report["overall"] == 72

    def test_end_interview_no_session(self, mock_llm):
        """没有面试会话时不应报错（agent 层面处理）"""
        pass  # end_interview 只在有 session 时被调用

    def test_parse_json_direct(self, mock_llm, sample_resume_text):
        session = InterviewSession(sample_resume_text, {"overall": 70, "dimensions": []}, llm_client=mock_llm)
        result = session._parse_json('{"overall": 85}')
        assert result["overall"] == 85

    def test_parse_json_markdown_block(self, mock_llm, sample_resume_text):
        session = InterviewSession(sample_resume_text, {"overall": 70, "dimensions": []}, llm_client=mock_llm)
        result = session._parse_json('```json\n{"overall": 90}\n```')
        assert result["overall"] == 90

    def test_parse_json_bare_braces(self, mock_llm, sample_resume_text):
        session = InterviewSession(sample_resume_text, {"overall": 70, "dimensions": []}, llm_client=mock_llm)
        result = session._parse_json('Some text {"overall": 75} more text')
        assert result["overall"] == 75

    def test_parse_json_failure(self, mock_llm, sample_resume_text):
        session = InterviewSession(sample_resume_text, {"overall": 70, "dimensions": []}, llm_client=mock_llm)
        result = session._parse_json("no json here at all")
        assert "error" in result


# ======================================================================
# InterviewAgent 测试
# ======================================================================

class TestInterviewAgentInit:
    """Agent 初始化"""

    def test_init(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        assert agent.name == "interview"
        assert agent._session is None
        assert agent.has_active_session is False

    def test_tool_definitions(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        tools = agent.get_tool_definitions()
        assert len(tools) == 3
        names = {t["function"]["name"] for t in tools}
        assert names == {"start_interview", "interview_chat", "end_interview"}

    def test_tool_names(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        assert agent.get_tool_names() == {"start_interview", "interview_chat", "end_interview"}


class TestInterviewAgentProcess:
    """process override 测试"""

    def test_process_bypasses_llm_when_session_active(self, mock_llm):
        """有活跃会话时直接 chat，不调用 LLM 路由"""
        agent = InterviewAgent(mock_llm)
        agent._session = MagicMock()
        agent._session.chat.return_value = "direct reply"
        result = agent.process("我的回答是...")
        assert result["type"] == "text"
        assert result["content"] == "direct reply"
        agent._session.chat.assert_called_once_with("我的回答是...")

    def test_process_uses_llm_when_no_session(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        agent.get_tool_definitions = MagicMock(return_value=INTERVIEW_TOOLS)
        result = agent.process("我想开始面试")
        assert result["type"] == "text"  # mock_llm returns text


class TestInterviewAgentToolDispatch:
    """工具派发测试"""

    def test_unknown_tool(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        result = agent.execute_tool("nonexistent")
        assert "error" in result

    def test_start_interview_dispatches(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        agent._tool_start_interview = MagicMock(return_value={"question": "Q1", "session_active": True})
        result = agent.execute_tool("start_interview", resume_text="test", category="ML")
        assert result["session_active"] is True

    def test_interview_chat_no_session(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        result = agent.execute_tool("interview_chat", message="hello")
        assert "error" in result

    def test_end_interview_no_session(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        result = agent.execute_tool("end_interview")
        assert "error" in result


class TestInterviewAgentToolStart:
    """_tool_start_interview 测试"""

    def test_start_creates_session(self, mock_llm, sample_resume_text):
        agent = InterviewAgent(mock_llm)
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = {"overall": 75, "dimensions": []}
        mock_kb = MagicMock()
        mock_kb.compare_with_excellent.return_value = {"excellent_count": 5}

        with patch("modules.resume_evaluator.ResumeEvaluator", return_value=mock_evaluator), \
             patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_start_interview(resume_text=sample_resume_text, category="ML")
            assert agent._session is not None
            assert result["session_active"] is True
            assert "question" in result
            assert "evaluation" in result

    def test_start_uses_injected_context(self, mock_llm, sample_resume_text, sample_evaluation_report):
        """Coordinator 注入的评估结果应优先使用"""
        agent = InterviewAgent(mock_llm)
        agent._shared_context = MagicMock()
        agent._shared_context.evaluation_result = {"overall": 88, "dimensions": []}

        mock_kb = MagicMock()
        mock_kb.compare_with_excellent.return_value = {"excellent_count": 3}
        # 不应调用 evaluator
        with patch("modules.resume_evaluator.ResumeEvaluator") as mock_ev, \
             patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_start_interview(resume_text=sample_resume_text, category="ML")
            mock_ev.assert_not_called()
            assert result["evaluation"]["overall"] == 88

    def test_start_handles_comparison_error(self, mock_llm, sample_resume_text):
        """优秀简历对比失败不应中断面试启动"""
        agent = InterviewAgent(mock_llm)
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.return_value = {"overall": 75, "dimensions": []}
        mock_kb = MagicMock()
        mock_kb.compare_with_excellent.side_effect = RuntimeError("KB error")

        with patch("modules.resume_evaluator.ResumeEvaluator", return_value=mock_evaluator), \
             patch.object(agent, '_get_module', return_value=mock_kb):
            result = agent._tool_start_interview(resume_text=sample_resume_text, category="ML")
            # 应该仍能成功，只是没有对比数据
            assert result["session_active"] is True


class TestInterviewAgentToolChat:
    """_tool_interview_chat 测试"""

    def test_chat_returns_reply(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        agent._session = MagicMock()
        agent._session.chat.return_value = "follow-up question"
        result = agent._tool_interview_chat(message="my answer")
        assert result["reply"] == "follow-up question"
        agent._session.chat.assert_called_once_with("my answer")


class TestInterviewAgentToolEnd:
    """_tool_end_interview 测试"""

    def test_end_returns_report(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        agent._session = MagicMock()
        agent._session.end_interview.return_value = {"overall": 80, "dimensions": {}, "stats": {}}
        result = agent._tool_end_interview()
        assert result["overall"] == 80
        # session 应被清空
        assert agent._session is None
        assert agent.has_active_session is False


class TestInterviewAgentGetMessages:
    """get_messages 测试"""

    def test_get_messages_no_session(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        assert agent.get_messages() == []

    def test_get_messages_with_session(self, mock_llm):
        agent = InterviewAgent(mock_llm)
        agent._session = MagicMock()
        agent._session.messages = [{"role": "user", "content": "hello"}]
        assert agent.get_messages() == [{"role": "user", "content": "hello"}]
