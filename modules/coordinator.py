"""AgentCoordinator — 多 Agent 协同编排层

管理 3 个专业化 Agent 的路由、上下文注入、管道编排。
API 完全向后兼容旧的 WorkflowAgent。
"""

import json
from typing import Optional

from modules.llm_client import LLMClient
from modules.agent_base import BaseAgent, ConversationContext, WorkflowState, WorkflowStep
from modules.analysis_agent import AnalysisAgent
from modules.evaluation_agent import EvaluationAgent
from modules.interview_agent import InterviewAgent


# ======================================================================
# 路由工具定义
# ======================================================================

ROUTING_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "route_to_analysis",
            "description": "路由到分析Agent：用户想解析简历文本、查询知识库样本/统计、或润色简历",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_evaluation",
            "description": "路由到评估Agent：用户想对简历进行多维度评分、保存优秀简历到收集库",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_interview",
            "description": "路由到面试Agent：用户想开始模拟面试、继续面试对话、结束面试",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ======================================================================
# AgentCoordinator
# ======================================================================

class AgentCoordinator:
    """多 Agent 协同编排器 — API 向后兼容 WorkflowAgent"""

    # 关键词预检表（零成本拦截常见意图，避免 LLM 路由漂移）
    _KEYWORD_ROUTES = {
        "analysis": [
            "解析", "查", "知识库", "样本", "统计", "润色", "优化",
            "rewrite", "parse", "polish", "knowledge", "sample",
            "看看", "读一下", "提取", "结构化", "内容",
        ],
        "evaluation": [
            "评分", "评估", "打分", "评价", "评测",
            "score", "evaluate",
            "评一下", "几分", "多少分", "好不好", "水平",
        ],
        "interview": [
            "面试", "模拟面试", "面一下",
            "interview", "开始面试", "继续面试", "结束面试",
        ],
    }

    def __init__(self, llm_client: LLMClient = None):
        self._llm = llm_client or LLMClient()

        # 创建 3 个专业化 Agent
        self.analysis_agent = AnalysisAgent(self._llm)
        self.evaluation_agent = EvaluationAgent(self._llm)
        self.interview_agent = InterviewAgent(self._llm)

        # 共享上下文 & 工作流状态
        self.conversation_context = ConversationContext()
        self.state = WorkflowState()

        # 注册表：工具名 → 所属 Agent
        self._tool_registry: dict[str, BaseAgent] = {}
        for agent in [self.analysis_agent, self.evaluation_agent, self.interview_agent]:
            for name in agent.get_tool_names():
                self._tool_registry[name] = agent

    @property
    def llm(self) -> LLMClient:
        """暴露 llm 属性供外部注入（如 ResumePolisher）"""
        return self._llm

    # ------------------------------------------------------------------
    # 智能路由
    # ------------------------------------------------------------------

    def process_user_request(self, user_message: str, context: dict = None) -> dict:
        """LLM 路由 → 转发到对应 Agent — 签名同 WorkflowAgent.process_user_request"""
        agent_name = self._route(user_message, context)

        # 路由不明确时反问用户确认
        if agent_name == "confirm":
            return {
                "type": "text",
                "content": (
                    "请问您想做什么？我可以帮您：\n\n"
                    "1. **解析/润色简历** — 提取结构化信息、优化表达\n"
                    "2. **评估打分** — 多维度评分并给出改进建议\n"
                    "3. **模拟面试** — 开始一场个性化面试\n\n"
                    "请告诉我您的需求。"
                ),
            }

        target = self._get_agent(agent_name)
        if not target:
            return {"type": "text", "content": f"无法路由请求，请重试"}

        # 注入共享上下文
        self._inject_context(target)

        # 面试 Agent 有活跃会话时直接走 process override
        return target.process(user_message, context)

    def _pre_route(self, user_message: str) -> str | None:
        """关键词预检：零成本匹配常见意图，命中则跳过 LLM 路由"""
        msg = user_message.lower()
        scores = {"analysis": 0, "evaluation": 0, "interview": 0}
        for agent, keywords in self._KEYWORD_ROUTES.items():
            for kw in keywords:
                if kw in msg:
                    scores[agent] += 1
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else None

    def _route(self, user_message: str, context: dict = None) -> str:
        """三级路由：关键词预检 → LLM 决策 → 反问兜底"""
        # Level 1: 关键词预检（零成本、零延迟、零出错）
        pre = self._pre_route(user_message)
        if pre:
            return pre

        # Level 2: LLM function calling 路由
        system = (
            "你是一个简历助手系统的智能路由协调员。你有三个专业Agent可用：\n"
            "1. analysis - 分析Agent：解析简历、查询知识库、润色简历\n"
            "2. evaluation - 评估Agent：对简历评分、保存优秀简历\n"
            "3. interview - 面试Agent：开始/继续/结束模拟面试\n"
            "分析用户请求，选择最合适的Agent来处理。如果用户需求涉及多个领域，选择最主要的那个。"
        )
        msgs = [{"role": "system", "content": system}]
        if context:
            msgs.append({"role": "system",
                         "content": f"上下文: {json.dumps(context, ensure_ascii=False)[:1000]}"})
        msgs.append({"role": "user", "content": user_message})

        try:
            resp = self._llm.chat(messages=msgs, tools=ROUTING_TOOLS,
                                  tool_choice="auto", temperature=0.2)
            choice = resp.choices[0]
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                name = choice.message.tool_calls[0].function.name
                return name.replace("route_to_", "")
        except Exception:
            pass

        # Level 3: 无法确定 → 反问用户确认
        return "confirm"

    def _get_agent(self, name: str) -> Optional[BaseAgent]:
        return {
            "analysis": self.analysis_agent,
            "evaluation": self.evaluation_agent,
            "interview": self.interview_agent,
        }.get(name)

    def _inject_context(self, agent: BaseAgent):
        """向 Agent 注入共享上下文"""
        agent._shared_context = self.conversation_context

    # ------------------------------------------------------------------
    # 直接工具派发
    # ------------------------------------------------------------------

    def execute_tool(self, tool_name: str, **kwargs) -> dict:
        """根据工具名找所属 Agent 派发 — 签名同 WorkflowAgent.execute_tool"""
        agent = self._tool_registry.get(tool_name)
        if not agent:
            return {"error": f"未知工具: {tool_name}"}
        try:
            return agent.execute_tool(tool_name, **kwargs)
        except Exception as e:
            return BaseAgent.format_error_summary(e, context=f"tool:{tool_name}")

    def get_tool_definitions(self) -> list:
        """返回全部工具的合并列表（兼容旧接口）"""
        tools = []
        for agent in [self.analysis_agent, self.evaluation_agent, self.interview_agent]:
            tools.extend(agent.get_tool_definitions())
        return tools

    # ------------------------------------------------------------------
    # 管道方法 — 跨 Agent 编排
    # ------------------------------------------------------------------

    def pipeline_full_evaluation(self, resume_text: str, category: str) -> dict:
        """全流程评估：AnalysisAgent(parse) → AnalysisAgent(samples) → EvaluationAgent(evaluate) → Coordinator(comparison)"""
        self.state = WorkflowState(workflow_name="full_evaluation", status="running")
        steps_def = [
            ("parse_resume", {"resume_text": resume_text}, self.analysis_agent),
            ("knowledge_samples", {"category": category, "query_type": "samples"}, self.analysis_agent),
            ("evaluate_resume", {"resume_text": resume_text, "category": category}, self.evaluation_agent),
        ]
        self.state.steps = [WorkflowStep(name=s[0]) for s in steps_def]

        for i, (step_name, kwargs, agent) in enumerate(steps_def):
            self.state.current_step_index = i
            step = self.state.steps[i]
            step.status = "running"
            try:
                result = agent.execute_tool(step_name, **kwargs)
                step.status = "completed"
                step.result = result
                self.state.accumulated_data[step_name] = result
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                self.state.status = "failed"
                self.state.error = str(e)
                return self._build_evaluation_report(error=str(e))

        # Step 4: 优秀简历对比（Coordinator 直接调用知识库）
        try:
            kb = self.analysis_agent._get_module("knowledge_base")
            comparison = kb.compare_with_excellent(resume_text, category)
            if comparison and not comparison.get("info"):
                self.state.accumulated_data["knowledge_comparison"] = comparison
        except Exception:
            pass

        self.state.status = "completed"
        return self._build_evaluation_report()

    def pipeline_interview_prep(self, resume_text: str, category: str) -> dict:
        """面试准备：full_evaluation → InterviewAgent(start_interview)"""
        eval_result = self.pipeline_full_evaluation(resume_text, category)

        if self.state.status == "failed":
            return eval_result

        # 注入评估结果到面试 Agent
        self.conversation_context.evaluation_result = self.state.accumulated_data
        self._inject_context(self.interview_agent)

        self.state.workflow_name = "interview_prep"
        interview_step = WorkflowStep(name="start_interview", status="running")
        self.state.steps.append(interview_step)
        self.state.current_step_index = len(self.state.steps) - 1

        try:
            interview = self.interview_agent.execute_tool("start_interview",
                                                           resume_text=resume_text,
                                                           category=category)
            interview_step.status = "completed"
            interview_step.result = interview
            self.state.status = "completed"
            return {
                "evaluation": eval_result,
                "interview": interview,
                "workflow_status": "completed",
            }
        except Exception as e:
            interview_step.status = "failed"
            interview_step.error = str(e)
            self.state.status = "failed"
            self.state.error = str(e)
            return {"evaluation": eval_result, "error": str(e), "workflow_status": "failed"}

    def pipeline_polish_and_evaluate(self, resume_text: str, category: str, focus: str = "") -> dict:
        """润色前后对比：EvaluationAgent(evaluate) → AnalysisAgent(polish) → EvaluationAgent(evaluate) → delta"""
        self.state = WorkflowState(workflow_name="polish_and_evaluate", status="running")

        # Step 1: 评估原始版
        before = self.evaluation_agent.execute_tool("evaluate_resume",
                                                      resume_text=resume_text, category=category)

        # Step 2: 润色
        polished_result = self.analysis_agent.execute_tool("polish_resume",
                                                            resume_text=resume_text, category=category, focus=focus)
        polished_text = polished_result.get("polished", resume_text)

        # Step 3: 评估润色版
        after = self.evaluation_agent.execute_tool("evaluate_resume",
                                                     resume_text=polished_text, category=category)

        # Step 4: 计算差异
        before_scores = {d["key"]: d["score"] for d in before.get("dimensions", [])}
        after_scores = {d["key"]: d["score"] for d in after.get("dimensions", [])}
        deltas = {}
        for key in before_scores:
            deltas[key] = {
                "before": before_scores[key],
                "after": after_scores.get(key, 0),
                "delta": after_scores.get(key, 0) - before_scores[key],
            }

        self.state.status = "completed"
        return {
            "before_evaluation": before,
            "after_evaluation": after,
            "polished_text": polished_text,
            "changes": polished_result.get("changes", []),
            "keywords_added": polished_result.get("keywords_added", []),
            "suggestions": polished_result.get("suggestions", []),
            "score_deltas": deltas,
            "overall_before": before.get("overall", 0),
            "overall_after": after.get("overall", 0),
            "overall_delta": after.get("overall", 0) - before.get("overall", 0),
            "workflow_status": "completed",
        }

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def get_state(self) -> WorkflowState:
        return self.state

    def reset_state(self):
        self.state = WorkflowState()

    def get_step_result(self, step_name: str) -> Optional[dict]:
        return self.state.accumulated_data.get(step_name)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _build_evaluation_report(self, error: str = None) -> dict:
        data = self.state.accumulated_data
        report = {
            "workflow_status": "completed" if not error else "failed",
            "workflow_progress": {"current": self.state.current_step_index, "total": len(self.state.steps)},
            "structured_resume": data.get("parse_resume", {}),
            "benchmark_count": data.get("knowledge_samples", {}).get("count", 0),
        }
        if error:
            report["error"] = error
            return report

        eval_data = data.get("evaluate_resume", {})
        report.update({
            "overall": eval_data.get("overall", 0),
            "weighted_score": eval_data.get("weighted_score", 0),
            "dimensions": eval_data.get("dimensions", []),
            "strengths": eval_data.get("strengths", []),
            "weaknesses": eval_data.get("weaknesses", []),
            "suggestions": eval_data.get("suggestions", []),
            "summary": eval_data.get("summary", ""),
        })

        comparison = data.get("knowledge_comparison", {})
        if comparison and not comparison.get("info"):
            report["excellent_comparison"] = comparison

        return report
