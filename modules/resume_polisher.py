"""简历润色模块 - 用 LLM 优化/润色简历"""

import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

POLISH_SYSTEM_PROMPT = """你是一位专业的简历优化专家。你的任务是根据目标岗位JD，优化候选人的简历。

## 优化原则
1. 使用强动词开头（如"主导"、"设计"、"实现"、"优化"、"搭建"）
2. 量化成果：每个项目/经历至少一个具体数据指标
3. STAR法则：情境-任务-行动-结果
4. 关键词匹配：融入目标岗位的高频技术关键词
5. 保持真实性：不要虚构经历，只优化表达方式
6. 简洁有力：每条描述控制在1-2行

## 输出格式
返回 JSON，不要其他内容：
{
    "polished": "润色后的完整简历文本",
    "changes": [
        {"original": "原内容片段", "improved": "优化后内容", "reason": "优化原因"}
    ],
    "keywords_added": ["新增关键词1", "新增关键词2"],
    "suggestions": ["整体建议1", "整体建议2"]
}"""


class ResumePolisher:
    """简历润色器"""

    def __init__(self, llm_client=None):
        if llm_client:
            self.client = llm_client.create_module_client()
            self.model = llm_client.model
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                try:
                    import streamlit as st
                    api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
                except ImportError:
                    pass
            self.client = OpenAI(
                api_key=api_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def polish(self, resume_text: str, category: str = "", focus: str = "") -> dict:
        """润色简历（非流式）"""
        reply = self._call_polish(resume_text, category, focus)
        return self._parse_result(reply)

    def polish_stream(self, resume_text: str, category: str = "", focus: str = ""):
        """流式润色，逐 token yield"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(resume_text, category, focus)},
            ],
            temperature=0.4,
            max_tokens=3072,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def _build_prompt(self, resume_text, category, focus):
        user_content = f"目标岗位: {category or '未指定'}\n\n简历内容:\n{resume_text[:4000]}"
        if focus:
            user_content += f"\n\n重点关注: {focus}"
        return user_content

    def _call_polish(self, resume_text, category, focus):
        user_content = self._build_prompt(resume_text, category, focus)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=3072,
        )
        return resp.choices[0].message.content

    @staticmethod
    def _parse_result(reply: str) -> dict:
        """解析 LLM 返回的 JSON"""
        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', reply, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"error": "解析失败", "polished": reply[:3000]}
