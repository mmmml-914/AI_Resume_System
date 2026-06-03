"""基础 Agent 类 — 所有 Agent 的基类 + 数据结构"""

import json
import traceback
from dataclasses import dataclass, field
from typing import Optional, Any

from modules.llm_client import LLMClient


# ======================================================================
# 消息 & 上下文数据结构
# ======================================================================

@dataclass
class AgentMessage:
    """Agent 间消息"""
    source: str = ""          # "analysis" | "evaluation" | "interview" | "coordinator" | "user"
    target: str = ""          # same enum
    message_type: str = ""    # "request" | "response" | "handoff"
    intent: str = ""          # tool name, "text", or "pipeline_result"
    payload: dict = field(default_factory=dict)
    correlation_id: str = ""
    pipeline_id: str = ""


@dataclass
class ConversationContext:
    """跨 Agent 共享上下文（由 Coordinator 注入）"""
    user_message: str = ""
    resume_text: str = ""
    category: str = ""
    evaluation_result: dict = field(default_factory=dict)
    interview_result: dict = field(default_factory=dict)
    polished_result: dict = field(default_factory=dict)
    shared_data: dict = field(default_factory=dict)
    active_agent: str = ""
    conversation_history: list = field(default_factory=list)


# ======================================================================
# 工作流状态
# ======================================================================

@dataclass
class WorkflowStep:
    """工作流中的单个步骤"""
    name: str = ""
    status: str = "pending"           # pending | running | completed | failed | skipped
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None


@dataclass
class WorkflowState:
    """工作流状态追踪"""
    workflow_name: str = ""
    status: str = "idle"              # idle | running | completed | failed
    steps: list = field(default_factory=list)   # list[WorkflowStep]
    current_step_index: int = 0
    accumulated_data: dict = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def progress(self) -> tuple:
        return (self.current_step_index, len(self.steps))

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "status": self.status,
            "current_step": self.current_step_index,
            "total_steps": len(self.steps),
            "error": self.error,
        }


# ======================================================================
# BaseAgent
# ======================================================================

class BaseAgent:
    """Agent 基类 — 提供 tool 注册/派发/LLM 路由框架"""

    def __init__(self, name: str, system_prompt: str, llm_client: LLMClient):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm_client
        self._modules: dict[str, Any] = {}
        self._shared_context: Optional[ConversationContext] = None

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list:
        raise NotImplementedError

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 工具命名辅助
    # ------------------------------------------------------------------

    def get_tool_names(self) -> set:
        return {t["function"]["name"] for t in self.get_tool_definitions()}

    # ------------------------------------------------------------------
    # LLM 智能路由（子类可 override）
    # ------------------------------------------------------------------

    def process(self, user_message: str, context: dict = None) -> dict:
        """LLM 根据用户自然语言决定调用哪个工具"""
        msgs = [{"role": "system", "content": self.system_prompt}]
        if context:
            msgs.append({"role": "system",
                         "content": f"上下文: {json.dumps(context, ensure_ascii=False)[:2000]}"})
        msgs.append({"role": "user", "content": user_message})

        resp = self.llm.chat(
            messages=msgs,
            tools=self.get_tool_definitions(),
            tool_choice="auto",
            temperature=0.3,
        )
        choice = resp.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            results = []
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                result = self.execute_tool(tc.function.name, **args)
                results.append({"tool": tc.function.name, "args": args, "result": result})
            return {"type": "tool_calls", "calls": results}

        return {"type": "text", "content": choice.message.content or ""}

    # ------------------------------------------------------------------
    # 懒加载共享模块
    # ------------------------------------------------------------------

    def _get_module(self, name: str):
        if name not in self._modules:
            if name == "evaluator":
                from modules.resume_evaluator import ResumeEvaluator
                self._modules[name] = ResumeEvaluator()
            elif name == "knowledge_base":
                from modules.knowledge_base import ResumeKnowledgeBase
                self._modules[name] = ResumeKnowledgeBase()
            elif name == "collector":
                from modules.resume_collector import ResumeCollector
                self._modules[name] = ResumeCollector()
            elif name == "polisher":
                from modules.resume_polisher import ResumePolisher
                self._modules[name] = ResumePolisher(llm_client=self.llm)
            elif name == "parser":
                from modules.resume_parser import extract_structured_info
                self._modules[name] = extract_structured_info
        return self._modules.get(name)

    # ------------------------------------------------------------------
    # 上下文注入
    # ------------------------------------------------------------------

    def set_context(self, key: str, value: Any):
        if self._shared_context is None:
            self._shared_context = ConversationContext()
        setattr(self._shared_context, key, value)

    # ------------------------------------------------------------------
    # 错误处理
    # ------------------------------------------------------------------

    @staticmethod
    def format_error_summary(error: Exception, context: str = "") -> dict:
        import openai as oa
        msg = str(error)
        if isinstance(error, oa.RateLimitError):
            suggestion = "API 频率限制，请稍后重试"
        elif isinstance(error, oa.APITimeoutError):
            suggestion = "请求超时，请检查网络连接"
        elif isinstance(error, oa.AuthenticationError):
            suggestion = "API Key 无效，请检查 .env 中的 DEEPSEEK_API_KEY"
        elif isinstance(error, oa.APIConnectionError):
            suggestion = "无法连接 API 服务器，请检查网络"
        elif isinstance(error, json.JSONDecodeError):
            suggestion = "LLM 返回了非 JSON 格式，请重试"
        else:
            suggestion = f"未知错误: {msg[:200]}"

        return {
            "error": True,
            "error_type": type(error).__name__,
            "error_message": msg[:300],
            "error_context": context,
            "suggested_action": suggestion,
        }
