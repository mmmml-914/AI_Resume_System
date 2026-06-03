"""共享 LLM 客户端 — 统一管理 API 调用、重试与超时"""

import os
import json
import time
import random
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    """共享 LLM 调用封装 — 统一管理 API 调用、重试与超时"""

    RETRYABLE_ERRORS = (
        __import__("openai", fromlist=["RateLimitError"]).RateLimitError,
        __import__("openai", fromlist=["APITimeoutError"]).APITimeoutError,
        __import__("openai", fromlist=["APIConnectionError"]).APIConnectionError,
    )

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=120, max_retries=1)

    def chat(self, messages: list, temperature: float = 0.3, max_tokens: int = 2048,
             tools: list = None, tool_choice: str = None) -> dict:
        """统一 chat 入口，带重试"""
        kwargs = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        def _call():
            return self.client.chat.completions.create(**kwargs)

        raw = self._call_with_retry(_call)
        return raw

    def chat_stream(self, messages: list, temperature: float = 0.7, max_tokens: int = 1024):
        """流式 chat，返回 content 块生成器"""
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def extract_json(self, messages: list, **kwargs) -> dict:
        """调用 LLM 并保证返回可解析的 JSON"""
        resp = self.chat(messages, **kwargs)
        reply = resp.choices[0].message.content

        try:
            return json.loads(reply)
        except json.JSONDecodeError:
            pass

        import re
        block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', reply, re.DOTALL)
        if block:
            try:
                return json.loads(block.group(1))
            except json.JSONDecodeError:
                pass

        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return {"error": "JSON 解析失败", "raw": reply[:500]}

    def create_module_client(self) -> OpenAI:
        """返回同配置的 OpenAI 客户端（用于注入旧模块）"""
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _call_with_retry(self, func, max_retries: int = 3, base_delay: float = 1.0):
        """指数退避重试"""
        import openai as oa

        last_exc = None
        for attempt in range(max_retries):
            try:
                return func()
            except self.RETRYABLE_ERRORS as e:
                last_exc = e
                if attempt == max_retries - 1:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
            except oa.APIStatusError as e:
                if e.status_code >= 500 and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    time.sleep(delay)
                else:
                    raise
            except Exception:
                raise
        raise last_exc
