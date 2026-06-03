"""共享 fixtures & mocks — 所有测试文件共用"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, PropertyMock, patch
from modules.llm_client import LLMClient


# ======================================================================
# Mock OpenAI chat completion response 构建工具
# ======================================================================

def make_mock_choice(text: str = "mock reply", finish_reason: str = "stop",
                     tool_calls: list = None):
    """构建一个 mock ChatCompletionChoice"""
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = text
    choice.message.tool_calls = tool_calls
    return choice


def make_mock_tool_call(name: str, args: dict = None):
    """构建一个 mock ToolCall"""
    import json
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args or {})
    return tc


def make_mock_chat_response(choices: list):
    """构建一个 mock ChatCompletion 响应"""
    resp = MagicMock()
    resp.choices = choices
    return resp


# ======================================================================
# Mock LLMClient
# ======================================================================

@pytest.fixture
def mock_llm():
    """创建一个受控的 mock LLMClient，默认返回纯文本响应"""
    client = MagicMock(spec=LLMClient)
    client.chat.return_value = make_mock_chat_response([
        make_mock_choice("mock response")
    ])
    client.model = "deepseek-chat"
    client.api_key = "sk-mock-key"
    client.base_url = "https://api.deepseek.com"

    # create_module_client 返回 mock OpenAI
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = make_mock_chat_response([
        make_mock_choice("mock openai response")
    ])
    client.create_module_client.return_value = mock_openai
    return client


@pytest.fixture
def mock_llm_with_tools():
    """mock LLMClient 返回 tool_calls"""
    def _make(tool_name: str = "parse_resume", args: dict = None,
              tool_text: str = None):
        client = MagicMock(spec=LLMClient)
        tc = make_mock_tool_call(tool_name, args or {})
        choice = make_mock_choice(
            text=tool_text or "",
            finish_reason="tool_calls",
            tool_calls=[tc],
        )
        client.chat.return_value = make_mock_chat_response([choice])
        client.model = "deepseek-chat"
        client.api_key = "sk-mock-key"
        client.base_url = "https://api.deepseek.com"

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.return_value = make_mock_chat_response([
            make_mock_choice("mock openai response")
        ])
        client.create_module_client.return_value = mock_openai
        return client
    return _make


# ======================================================================
# Mock modules (避免文件 I/O 依赖)
# ======================================================================

@pytest.fixture(autouse=True)
def mock_data_files():
    """自动 mock 所有读写文件的模块，防止测试写入真实数据"""
    with patch("modules.resume_collector.ResumeCollector._save"), \
         patch("modules.record_manager.RecordsManager._save"), \
         patch("modules.record_manager.RecordsManager._load"), \
         patch("modules.knowledge_base.ResumeKnowledgeBase._load_kaggle"), \
         patch("modules.knowledge_base.ResumeKnowledgeBase._load_excellent"):
        yield


@pytest.fixture
def sample_resume_text():
    return """Skills: Python, SQL, Machine Learning, PyTorch, TensorFlow

Education:
M.S. in Computer Science | Example University | 2024-2026
B.S. in Mathematics | State University | 2020-2024

Experience:
Data Scientist Intern | Tech Corp | 2025.06-2025.09
• Built ML model for user churn prediction, achieved 85% accuracy
• Designed A/B testing framework, improved CTR by 15%
• Developed ETL pipeline processing 500K daily records

Projects:
NLP Sentiment Analysis
• Implemented BERT-based sentiment classifier on 1M+ reviews
• Deployed with FastAPI, reduced inference latency by 40%
"""


@pytest.fixture
def sample_evaluation_report():
    return {
        "overall": 76,
        "weighted_score": 76.0,
        "dimensions": [
            {"key": "skills_match", "label": "技能匹配度", "score": 78, "weight": 0.30},
            {"key": "project_quality", "label": "项目经验质量", "score": 72, "weight": 0.25},
            {"key": "format_readability", "label": "格式与可读性", "score": 80, "weight": 0.15},
            {"key": "education", "label": "教育背景", "score": 85, "weight": 0.15},
            {"key": "expression", "label": "内容表达", "score": 70, "weight": 0.15},
        ],
        "strengths": ["技能覆盖面广", "有量化成果"],
        "weaknesses": ["项目描述缺乏技术深度", "表达不够简洁"],
        "suggestions": ["增加模型评估指标", "突出技术难点"],
        "summary": "整体表现良好，有提升空间",
        "n_samples": 1,
    }
