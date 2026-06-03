"""ResumePolisher 润色模块测试（仅单元测试，不调用 LLM）"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import json
from unittest.mock import MagicMock, patch
from modules.resume_polisher import ResumePolisher


class TestPolisherParseResult:
    """_parse_result 静态方法 — JSON 解析能力"""

    def test_parse_valid_json(self):
        text = '{"polished": "new text", "changes": [], "keywords_added": ["Python"], "suggestions": []}'
        result = ResumePolisher._parse_result(text)
        assert result["polished"] == "new text"
        assert result["keywords_added"] == ["Python"]

    def test_parse_markdown_json_block(self):
        text = '```json\n{"polished": "improved", "changes": [], "keywords_added": [], "suggestions": []}\n```'
        result = ResumePolisher._parse_result(text)
        assert result["polished"] == "improved"

    def test_parse_bare_braces(self):
        text = 'Some text before {"polished": "found", "changes": [], "keywords_added": [], "suggestions": []} after'
        result = ResumePolisher._parse_result(text)
        assert result["polished"] == "found"

    def test_parse_invalid_json_fallback(self):
        """非 JSON 内容返回 error + 原文截断"""
        text = "Hello world this is not json"
        result = ResumePolisher._parse_result(text)
        assert "error" in result
        assert result["polished"] == text[:3000]

    def test_parse_minimal_json(self):
        text = '{"polished": "short"}'
        result = ResumePolisher._parse_result(text)
        assert result["polished"] == "short"

    def test_parse_with_changes(self):
        text = json.dumps({
            "polished": "new resume",
            "changes": [
                {"original": "did work", "improved": "led project", "reason": "强动词"},
                {"original": "helped team", "improved": "optimized team workflow", "reason": "量化"},
            ],
            "keywords_added": ["Python", "TensorFlow"],
            "suggestions": ["增加更多量化数据"],
        })
        result = ResumePolisher._parse_result(text)
        assert len(result["changes"]) == 2
        assert result["changes"][0]["original"] == "did work"
        assert len(result["keywords_added"]) == 2


class TestPolisherBuildPrompt:
    """_build_prompt 测试"""

    def test_build_prompt_basic(self):
        polisher = ResumePolisher(llm_client=MagicMock())
        prompt = polisher._build_prompt("my resume text", "Data Science", "")
        assert "Data Science" in prompt
        assert "my resume text" in prompt

    def test_build_prompt_with_focus(self):
        polisher = ResumePolisher(llm_client=MagicMock())
        prompt = polisher._build_prompt("text", "ML", "突出量化成果")
        assert "突出量化成果" in prompt

    def test_build_prompt_no_category(self):
        polisher = ResumePolisher(llm_client=MagicMock())
        prompt = polisher._build_prompt("text", "", "")
        assert "未指定" in prompt

    def test_build_prompt_truncates_long_text(self):
        polisher = ResumePolisher(llm_client=MagicMock())
        long_text = "A" * 5000
        prompt = polisher._build_prompt(long_text, "ML", "")
        # text 应该被截断到 4000 字符
        assert len(prompt) < 4500


class TestPolisherStream:
    """流式润色测试"""

    def test_polish_stream_yields_tokens(self):
        """验证流式调用的基本行为"""
        mock_client = MagicMock()
        # 模拟流式返回
        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta.content = "improved"
        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta.content = " resume"
        chunk3 = MagicMock()
        chunk3.choices = [MagicMock()]
        chunk3.choices[0].delta.content = None  # 流结束

        mock_client.chat.completions.create.return_value = [chunk1, chunk2, chunk3]
        polisher = ResumePolisher(llm_client=MagicMock())
        polisher.client = mock_client

        tokens = list(polisher.polish_stream("original text", "ML"))
        assert len(tokens) == 2
        assert "".join(tokens) == "improved resume"
