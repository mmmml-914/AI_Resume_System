"""分析 Agent — 简历解析、知识库查询、润色"""

from modules.agent_base import BaseAgent
from modules.llm_client import LLMClient


ANALYSIS_SYSTEM_PROMPT = """你是一位专业的简历分析专家。你拥有以下能力：
1. 解析简历文本，提取结构化信息（姓名、学历、技能、项目经历等）
2. 查询知识库，获取同类岗位的样本简历、统计数据、优秀简历平均分
3. AI润色简历，优化表达、强化量化成果、匹配目标岗位关键词

请分析用户需求，调用合适的工具来完成任务。"""

ANALYSIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "parse_resume",
            "description": "解析简历文本，提取结构化信息：姓名、学历、学校、专业、技能、工作经历、项目、证书、目标岗位",
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_text": {"type": "string", "description": "简历原始文本"},
                },
                "required": ["resume_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_lookup",
            "description": "查询知识库：获取 Kaggle 同类简历样本、岗位统计数据、优秀简历平均分、或进行简历对比",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "岗位类别"},
                    "query_type": {
                        "type": "string",
                        "enum": ["samples", "stats", "excellent_avg", "comparison"],
                        "description": "samples=同类样本, stats=分布统计, excellent_avg=优秀简历均分, comparison=对比分析",
                    },
                    "resume_text": {"type": "string", "description": "对比分析时需要传入简历文本"},
                },
                "required": ["category", "query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "polish_resume",
            "description": "AI 润色简历：强化动词、量化成果、优化STAR法则表达、融入目标岗位关键词",
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_text": {"type": "string", "description": "原始简历文本"},
                    "category": {"type": "string", "description": "目标岗位类别"},
                    "focus": {"type": "string", "description": "可选：重点关注方向（如'突出量化成果'）"},
                },
                "required": ["resume_text", "category"],
            },
        },
    },
]


class AnalysisAgent(BaseAgent):
    """分析 Agent：解析简历、知识库查询、润色"""

    def __init__(self, llm_client: LLMClient):
        super().__init__("analysis", ANALYSIS_SYSTEM_PROMPT, llm_client)

    def get_tool_definitions(self) -> list:
        return ANALYSIS_TOOLS

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        tool_map = {
            "parse_resume": self._tool_parse_resume,
            "knowledge_lookup": self._tool_knowledge_lookup,
            "polish_resume": self._tool_polish,
        }
        handler = tool_map.get(tool_name)
        if not handler:
            return {"error": f"AnalysisAgent: 未知工具 {tool_name}"}
        try:
            return handler(**kwargs)
        except Exception as e:
            return self.format_error_summary(e, context=f"analysis:{tool_name}")

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _tool_parse_resume(self, resume_text: str, **kwargs) -> dict:
        extract = self._get_module("parser")
        result = extract(resume_text, api_key=self.llm.api_key, base_url=self.llm.base_url)
        return result if isinstance(result, dict) else {"parsed": result}

    def _tool_knowledge_lookup(self, category: str, query_type: str = "samples",
                               resume_text: str = None, **kwargs) -> dict:
        kb = self._get_module("knowledge_base")

        if query_type == "samples":
            samples = kb.get_sample_resumes(category, n=3)
            return {"samples": samples, "count": len(samples)}
        elif query_type == "stats":
            return kb.get_category_stats()
        elif query_type == "excellent_avg":
            avg = kb.get_excellent_avg_scores(category)
            return {"avg_scores": avg or {}}
        elif query_type == "comparison" and resume_text:
            result = kb.compare_with_excellent(resume_text, category)
            return result or {"info": "无对比数据"}
        return {"info": "未知查询类型"}

    def _tool_polish(self, resume_text: str, category: str = "",
                     focus: str = "", **kwargs) -> dict:
        polisher = self._get_module("polisher")
        return polisher.polish(resume_text, category, focus)

    def polish_stream(self, resume_text: str, category: str = "", focus: str = ""):
        """流式润色 — 供 UI 层逐字展示进度"""
        polisher = self._get_module("polisher")
        return polisher.polish_stream(resume_text, category, focus)

    @staticmethod
    def parse_polish_result(reply: str) -> dict:
        """解析流式润色的 LLM 返回 JSON"""
        from modules.resume_polisher import ResumePolisher
        return ResumePolisher._parse_result(reply)
