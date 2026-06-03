"""BaseAgent 基础类单元测试"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from modules.agent_base import (
    BaseAgent, AgentMessage, ConversationContext,
    WorkflowStep, WorkflowState,
)
from modules.llm_client import LLMClient


class TestAgentMessage:
    """AgentMessage 数据类"""

    def test_defaults(self):
        msg = AgentMessage()
        assert msg.source == ""
        assert msg.target == ""
        assert msg.message_type == ""
        assert msg.payload == {}
        assert msg.correlation_id == ""

    def test_with_values(self):
        msg = AgentMessage(
            source="analysis", target="coordinator",
            message_type="response", intent="parse_resume",
            payload={"skills": ["Python"]}, correlation_id="abc-123",
        )
        assert msg.source == "analysis"
        assert msg.payload["skills"] == ["Python"]


class TestConversationContext:
    """ConversationContext 数据类"""

    def test_defaults(self):
        ctx = ConversationContext()
        assert ctx.user_message == ""
        assert ctx.resume_text == ""
        assert ctx.evaluation_result == {}
        assert ctx.shared_data == {}

    def test_assign_fields(self):
        ctx = ConversationContext()
        ctx.resume_text = "some resume"
        ctx.evaluation_result = {"overall": 85}
        assert ctx.resume_text == "some resume"
        assert ctx.evaluation_result["overall"] == 85


class TestWorkflowStep:
    """WorkflowStep 数据类"""

    def test_defaults(self):
        step = WorkflowStep()
        assert step.name == ""
        assert step.status == "pending"
        assert step.result is None
        assert step.error is None

    def test_completed_step(self):
        step = WorkflowStep(name="parse", status="completed",
                            result={"skills": ["Py"]})
        assert step.name == "parse"
        assert step.status == "completed"


class TestWorkflowState:
    """WorkflowState 数据类"""

    def test_defaults(self):
        state = WorkflowState()
        assert state.status == "idle"
        assert state.steps == []
        assert state.progress == (0, 0)

    def test_progress(self):
        state = WorkflowState()
        state.steps = [WorkflowStep(), WorkflowStep(), WorkflowStep()]
        state.current_step_index = 1
        assert state.progress == (1, 3)

    def test_to_dict(self):
        state = WorkflowState(
            workflow_name="test_flow", status="running",
            current_step_index=2,
        )
        state.steps = [WorkflowStep(), WorkflowStep(), WorkflowStep()]
        d = state.to_dict()
        assert d["workflow_name"] == "test_flow"
        assert d["status"] == "running"
        assert d["current_step"] == 2
        assert d["total_steps"] == 3


SYS_PROMPT = "You are a test agent."
MOCK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "test_tool",
            "description": "Test tool",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}},
                           "required": ["x"]},
        },
    },
]


class ConcreteAgent(BaseAgent):
    """具体的测试 Agent 实现"""

    def get_tool_definitions(self) -> list:
        return MOCK_TOOLS

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        if tool_name == "test_tool":
            return {"result": f"processed {kwargs.get('x', '')}"}
        return {"error": "unknown tool"}


class TestBaseAgent:
    """BaseAgent 核心功能"""

    def test_init(self, mock_llm):
        agent = ConcreteAgent("test_agent", SYS_PROMPT, mock_llm)
        assert agent.name == "test_agent"
        assert agent.system_prompt == SYS_PROMPT
        assert agent.llm is mock_llm
        assert agent._modules == {}
        assert agent._shared_context is None

    def test_get_tool_names(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        assert agent.get_tool_names() == {"test_tool"}

    def test_get_tool_definitions(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        tools = agent.get_tool_definitions()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "test_tool"

    def test_execute_tool_known(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        result = agent.execute_tool("test_tool", x="hello")
        assert result["result"] == "processed hello"

    def test_execute_tool_unknown(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        result = agent.execute_tool("nonexistent")
        assert "error" in result

    def test_set_context(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        agent.set_context("resume_text", "my resume")
        assert agent._shared_context.resume_text == "my resume"

    def test_set_context_creates_if_none(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        assert agent._shared_context is None
        agent.set_context("key", "val")
        assert agent._shared_context is not None
        assert agent._shared_context.key == "val"

    def test_process_text_response(self, mock_llm):
        """process 返回纯文本时正确解析"""
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        result = agent.process("hello")
        assert result["type"] == "text"
        assert "mock response" in result["content"]

    def test_process_tool_call(self, mock_llm_with_tools):
        """process 返回 tool_call 时执行工具并返回结果"""
        mock_llm = mock_llm_with_tools("test_tool", {"x": "world"})
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        result = agent.process("do tool")
        assert result["type"] == "tool_calls"
        assert len(result["calls"]) == 1
        assert result["calls"][0]["tool"] == "test_tool"
        assert result["calls"][0]["result"]["result"] == "processed world"

    def test_process_with_context(self, mock_llm):
        """context 参数被注入到 system prompt"""
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        agent.process("hello", context={"resume_text": "some text"})
        # LLM 被调用时应该包含上下文
        call_kwargs = mock_llm.chat.call_args
        msgs = call_kwargs[1]["messages"]
        assert len(msgs) == 3  # system + context + user
        assert "上下文" in msgs[1]["content"]

    def test_get_module_evaluator(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        with patch("modules.resume_evaluator.ResumeEvaluator") as mock_ev:
            mod = agent._get_module("evaluator")
            assert mod is not None

    def test_get_module_knowledge_base(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        with patch("modules.knowledge_base.ResumeKnowledgeBase") as mock_kb:
            mod = agent._get_module("knowledge_base")
            assert mod is not None

    def test_get_module_caches(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        with patch("modules.resume_evaluator.ResumeEvaluator") as mock_ev:
            m1 = agent._get_module("evaluator")
            m2 = agent._get_module("evaluator")
            assert m1 is m2  # same instance from cache

    def test_get_module_unknown(self, mock_llm):
        agent = ConcreteAgent("test", SYS_PROMPT, mock_llm)
        mod = agent._get_module("nonexistent")
        assert mod is None


class TestFormatErrorSummary:
    """format_error_summary 静态方法"""

    def test_rate_limit(self):
        import openai as oa
        err = oa.RateLimitError("rate limited", response=MagicMock(), body={})
        result = BaseAgent.format_error_summary(err)
        assert result["error"] is True
        assert result["error_type"] == "RateLimitError"
        assert "频率限制" in result["suggested_action"]

    def test_authentication_error(self):
        import openai as oa
        err = oa.AuthenticationError("bad key", response=MagicMock(), body={})
        result = BaseAgent.format_error_summary(err)
        assert "API Key 无效" in result["suggested_action"]

    def test_generic_error(self):
        err = ValueError("something broke")
        result = BaseAgent.format_error_summary(err, context="test")
        assert result["error"] is True
        assert result["error_type"] == "ValueError"
        assert "something broke" in result["error_message"]
        assert result["error_context"] == "test"

    def test_json_decode_error(self):
        err = json.JSONDecodeError("bad json", "", 0)
        result = BaseAgent.format_error_summary(err)
        assert "非 JSON" in result["suggested_action"]
