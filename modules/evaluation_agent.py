"""评估 Agent — 简历评分、优秀简历采集"""

import time

from modules.agent_base import BaseAgent
from modules.llm_client import LLMClient


EVALUATION_SYSTEM_PROMPT = """你是一位严谨的简历评估专家。你拥有以下能力：
1. 对简历进行多维度评分（技能匹配度、项目经验质量、格式与可读性、教育背景、内容表达）
2. 保存优秀简历到收集库，用于后续评估对照

请分析用户需求，调用合适的工具来完成任务。"""

EVALUATION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_resume",
            "description": "对简历进行5维度评分：技能匹配度、项目经验质量、格式与可读性、教育背景、内容表达",
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_text": {"type": "string", "description": "简历全文"},
                    "category": {"type": "string", "description": "目标岗位类别"},
                },
                "required": ["resume_text", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "collect_resume",
            "description": "保存优秀简历到收集库，用于后续评估对照",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "岗位类别"},
                    "title": {"type": "string", "description": "简历标题"},
                    "source": {"type": "string", "description": "来源平台"},
                    "resume_text": {"type": "string", "description": "简历全文"},
                    "background": {"type": "string", "description": "候选人的背景简介"},
                },
                "required": ["category", "title", "source", "resume_text"],
            },
        },
    },
]


class EvaluationAgent(BaseAgent):
    """评估 Agent：对简历评分、收集优秀简历"""

    def __init__(self, llm_client: LLMClient):
        super().__init__("evaluation", EVALUATION_SYSTEM_PROMPT, llm_client)

    def get_tool_definitions(self) -> list:
        return EVALUATION_TOOLS

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        tool_map = {
            "evaluate_resume": self._tool_evaluate,
            "collect_resume": self._tool_collect,
        }
        handler = tool_map.get(tool_name)
        if not handler:
            return {"error": f"EvaluationAgent: 未知工具 {tool_name}"}
        try:
            return handler(**kwargs)
        except Exception as e:
            return self.format_error_summary(e, context=f"evaluation:{tool_name}")

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _tool_evaluate(self, resume_text: str, category: str,
                       n_samples: int = 1, **kwargs) -> dict:
        evaluator = self._get_module("evaluator")
        return evaluator.evaluate(resume_text, category, n_samples=n_samples)

    def _tool_collect(self, category: str, title: str, source: str,
                      resume_text: str, background: str = "", **kwargs) -> dict:
        collector = self._get_module("collector")
        entry = {
            "id": f"agent_{int(time.time())}",
            "category": category,
            "title": title,
            "quality": "excellent",
            "source": source,
            "background": background,
            "resume_text": resume_text,
            "features": {
                "quantification": any(kw in resume_text for kw in ["%", "提升", "增长", "万", "亿", "倍"]),
                "star_method": any(kw in resume_text for kw in ["•", "·", "-"]),
            },
        }
        collector.add(entry)
        return {"success": True, "id": entry["id"]}
