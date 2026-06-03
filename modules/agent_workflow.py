"""向后兼容桥接模块 — 所有类从新模块重新导出

使用方式不变：
    from modules.agent_workflow import WorkflowAgent, LLMClient, WorkflowState
"""

from modules.llm_client import LLMClient
from modules.agent_base import WorkflowStep, WorkflowState, ConversationContext
from modules.coordinator import AgentCoordinator as WorkflowAgent

__all__ = ["LLMClient", "WorkflowStep", "WorkflowState", "ConversationContext", "WorkflowAgent"]
