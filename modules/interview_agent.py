"""模拟面试引擎 - 基于简历评估结果的个性化面试"""

import os
import json
import re
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from modules.agent_base import BaseAgent

load_dotenv()

INTERVIEWER_SYSTEM_PROMPT = """你是一名资深的技术面试官，正在模拟一场真实的一对一专业面试。

## 你的职责
1. 基于候选人的简历和【评估报告】提出有深度的技术问题
2. 重点考察评估报告中显示薄弱的维度
3. 针对候选人的回答给出简短反馈并继续提问
4. 每次只问一个问题，等待候选人回答后再继续

## 面试流程
- 开场：简要介绍，立即提出第一个技术问题
- 技术提问：覆盖简历中的技能、项目、业务理解
- 深入追问：根据回答质量决定是否深入
- 结束：由候选人决定结束面试

## 提问原则
- 问题必须与简历具体内容相关，不要问泛泛的问题
- 优先考察"为什么"和"怎么做"而非简单定义
- 如果候选人回答不准确，可以适当追问但保持友善
- 每次只问一个问题，用 ? 结尾
- 语言：与简历语言一致（英文简历用英文提问，中文简历用中文提问）"""

REPORT_SYSTEM_PROMPT = """你是一位面试评估专家。基于面试对话记录，生成一份结构化的面试评估报告。

评估维度：
1. technical_accuracy（技术准确性）：技术概念理解是否准确、深度如何
2. communication（沟通表达）：回答是否清晰有条理、是否使用STAR法则
3. problem_solving（问题解决能力）：面对问题时能否结构化思考、是否有解决方案
4. domain_knowledge（领域知识）：对目标岗位所在领域的理解深度

评分标准：
- 80-100：优秀，远超预期
- 60-79：良好，达到预期
- 40-59：一般，有提升空间
- 0-39：较差，需要大幅提升

返回 JSON 格式，不要其他内容：
{
    "overall": <0-100>,
    "dimensions": {
        "technical_accuracy": {"score": <int>, "comment": "<评语>"},
        "communication": {"score": <int>, "comment": "<评语>"},
        "problem_solving": {"score": <int>, "comment": "<评语>"},
        "domain_knowledge": {"score": <int>, "comment": "<评语>"}
    },
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["不足1", "不足2"],
    "suggestions": ["建议1", "建议2"],
    "evaluation_gaps": "与简历评估的差异分析：面试表现哪些地方优于/劣于简历呈现"
}"""


class InterviewSession:
    """面试会话 - 基于简历评估结果进行个性化面试"""

    def __init__(self, resume_text: str, evaluation_report: dict, llm_client=None):
        if llm_client:
            self.client = llm_client.create_module_client()
            self.model = llm_client.model
        else:
            self.client = OpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.resume_text = resume_text
        self.evaluation = evaluation_report
        self.messages = []

    def _build_personalized_prompt(self) -> str:
        """根据评估结果构建个性化面试提示"""
        report = self.evaluation
        dims = report.get("dimensions", [])
        weaknesses = report.get("weaknesses", [])

        # 找出强项和弱项维度
        weak_areas = []
        strong_areas = []
        for d in dims:
            label = d.get("label", d.get("key", ""))
            score = d.get("score", 0)
            if score < 70:
                weak_areas.append(f"{label}({score}分)")
            else:
                strong_areas.append(f"{label}({score}分)")

        prompt = INTERVIEWER_SYSTEM_PROMPT

        if weak_areas:
            prompt += f"""

## 个性化面试重点（基于评估报告）
候选人的以下维度评分较低，请重点考察：
- {'、'.join(weak_areas)}

针对这些薄弱环节，深入追问相关项目经验和技术细节。"""

        if strong_areas:
            prompt += f"""

候选人以下维度表现较好，可适当快速验证：
- {'、'.join(strong_areas)}"""

        if weaknesses:
            prompt += f"""

## 评估报告指出的具体不足
{'、'.join(weaknesses[:3])}
请围绕这些不足设计问题，考察候选人是否确实存在这些短板。"""

        return prompt

    def start(self) -> str:
        """开始面试，返回第一个问题"""
        system_prompt = self._build_personalized_prompt()

        # 找一份优秀简历作为参考提分线索
        excellent_context = ""
        if self.evaluation.get("excellent_comparison"):
            avg = self.evaluation["excellent_comparison"].get("avg_scores", {})
            if avg:
                gaps = []
                for d in self.evaluation.get("dimensions", []):
                    key = d.get("key")
                    if key and key in avg:
                        gap = avg[key] - d.get("score", 0)
                        if gap > 0:
                            gaps.append(f"{d.get('label', key)}低于优秀均值{gap:.0f}分")
                if gaps:
                    excellent_context = "\n\n## 与优秀简历的差距\n" + "\n".join(gaps)

        user_content = (
            f"这是候选人的简历：\n\n{self.resume_text[:3000]}"
            f"\n\n这是简历评估报告（评分0-100）：\n{json.dumps(self.evaluation, ensure_ascii=False, indent=2)[:2000]}"
            f"{excellent_context}"
            f"\n\n请开始面试。先简短开场（一句话介绍自己），然后立即提出第一个技术问题。"
        )

        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        reply = self._call_llm()
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def chat(self, user_message: str) -> str:
        """候选人回答，返回面试官回应"""
        self.messages.append({"role": "user", "content": user_message})
        reply = self._call_llm()
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    def _call_llm(self, max_tokens: int = 1024) -> str:
        """调用 LLM"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=0.7,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content

    def _call_llm_stream(self, max_tokens: int = 1024):
        """流式调用 LLM，逐 chunk 产出 content"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            temperature=0.7,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def chat_stream(self, user_message: str):
        """候选人回答，流式返回面试官回应（yield 逐字）+ 自动记入历史"""
        self.messages.append({"role": "user", "content": user_message})
        full = ""
        for token in self._call_llm_stream():
            full += token
            yield token
        self.messages.append({"role": "assistant", "content": full})

    def end_interview(self) -> dict:
        """结束面试，生成评估报告"""
        # 提取 Q&A 对话（跳过 system prompt 和初始 user 消息）
        qa_pairs = []
        i = 0
        for m in self.messages:
            if m["role"] == "system":
                continue
            if i == 0 and m["role"] == "user":
                i += 1  # skip the initial context message
                continue
            qa_pairs.append(f"[{'面试官' if m['role'] == 'assistant' else '候选人'}]: {m['content'][:500]}")
            i += 1

        dialogue = "\n\n".join(qa_pairs[-10:])  # only last 10 exchanges

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": f"这是面试对话记录：\n\n{dialogue}\n\n请生成评估报告，只返回JSON。"},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        reply = resp.choices[0].message.content

        # 尝试多种方式解析 JSON
        result = self._parse_json(reply)
        if "error" in result:
            return result

        # 添加对话统计
        user_msgs = [m for m in self.messages if m["role"] == "user"]
        result["stats"] = {
            "total_questions": len(user_msgs) - 1,  # minus initial context
            "conversation_length": len(self.messages),
        }
        return result

    def _parse_json(self, text: str) -> dict:
        """从 LLM 回复中提取 JSON"""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block
        import re
        # Match ```json ... ``` block
        block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if block:
            try:
                return json.loads(block.group(1))
            except json.JSONDecodeError:
                pass

        # Match bare { ... }
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {"error": "无法解析报告", "raw": text[:500]}

    def get_recent_context(self, n: int = 6) -> list:
        """获取最近 n 条对话记录用于显示"""
        recent = self.messages[-n:] if len(self.messages) > n else self.messages[1:]
        return [m for m in recent if m["role"] in ("user", "assistant")]


# ======================================================================
# InterviewAgent — 面试管理 Agent（多 Agent 协同用）
# ======================================================================

INTERVIEW_AGENT_SYSTEM_PROMPT = """你是一位面试管理 Agent。你负责：
1. 基于简历评估结果启动个性化模拟面试
2. 管理面试对话流程
3. 结束面试并生成评估报告

分析用户需求，调用合适的工具来完成任务。"""

INTERVIEW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_interview",
            "description": "基于简历评估结果启动个性化模拟面试，返回面试官的第一个问题",
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
            "name": "interview_chat",
            "description": "在面试对话中发送候选人回答，返回面试官的回应",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "候选人的回答内容"},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_interview",
            "description": "结束当前面试，生成结构化面试评估报告",
            "parameters": {
                "type": "object",
                "properties": {
                    "dummy": {"type": "string", "description": "忽略"},
                },
            },
        },
    },
]


class InterviewAgent(BaseAgent):
    """面试 Agent：启动/管理/结束面试会话"""

    def __init__(self, llm_client):
        super().__init__("interview", INTERVIEW_AGENT_SYSTEM_PROMPT, llm_client)
        self._session: Optional[InterviewSession] = None

    def get_tool_definitions(self) -> list:
        return INTERVIEW_TOOLS

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        tool_map = {
            "start_interview": self._tool_start_interview,
            "interview_chat": self._tool_interview_chat,
            "end_interview": self._tool_end_interview,
        }
        handler = tool_map.get(tool_name)
        if not handler:
            return {"error": f"InterviewAgent: 未知工具 {tool_name}"}
        try:
            return handler(**kwargs)
        except Exception as e:
            return BaseAgent.format_error_summary(e, context=f"interview:{tool_name}")

    def process(self, user_message: str, context: dict = None) -> dict:
        """Override: 有活跃会话时绕过 LLM 路由直接 chat，降低延迟。
        检测明显的非面试意图，避免把"帮我评分"当成面试回答。"""
        if self._session is not None:
            non_interview_kw = [
                "评分", "评估", "打分", "润色", "解析简历", "知识库",
                "批量", "看板", "统计", "采集", "polish", "evaluate",
                "parse", "score", "总览", "数据",
            ]
            msg_lower = user_message.lower()
            if any(kw in msg_lower for kw in non_interview_kw):
                return {
                    "type": "text",
                    "content": (
                        "您当前正在面试中。请先输入 **结束面试** 生成面试报告，"
                        "然后再进行其他操作。"
                    ),
                }
            reply = self._session.chat(user_message)
            return {"type": "text", "content": reply}
        return super().process(user_message, context)

    @property
    def has_active_session(self) -> bool:
        return self._session is not None

    def get_messages(self) -> list:
        """获取当前面试对话历史"""
        if not self._session:
            return []
        return self._session.messages

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _tool_start_interview(self, resume_text: str, category: str, **kwargs) -> dict:
        from modules.resume_evaluator import ResumeEvaluator

        if self._session is not None:
            return {"error": "已有活跃面试会话，请先结束当前面试再开始新的面试"}
        eval_result = {}
        if self._shared_context and self._shared_context.evaluation_result:
            eval_result = self._shared_context.evaluation_result
        else:
            evaluator = ResumeEvaluator()
            eval_result = evaluator.evaluate(resume_text, category)

        # 优秀简历对比
        kb = self._get_module("knowledge_base")
        try:
            excellent_cmp = kb.compare_with_excellent(resume_text, category)
            if excellent_cmp:
                eval_result["excellent_comparison"] = excellent_cmp
        except Exception:
            pass

        session = InterviewSession(resume_text, eval_result, llm_client=self.llm)
        self._session = session
        first_q = session.start()

        return {
            "question": first_q,
            "evaluation": eval_result,
            "session_active": True,
        }

    def _tool_interview_chat(self, message: str, **kwargs) -> dict:
        if not self._session:
            return {"error": "没有活跃的面试会话"}
        reply = self._session.chat(message)
        return {"reply": reply}

    def _tool_end_interview(self, **kwargs) -> dict:
        if not self._session:
            return {"error": "没有活跃的面试会话"}
        report = self._session.end_interview()
        self._session = None
        return report
