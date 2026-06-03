"""配置管理"""
import os
from dotenv import load_dotenv

load_dotenv()

# 评估维度权重（基于学术论文）
EVAL_WEIGHTS = {
    "skills_match": {"label": "技能匹配度", "weight": 0.30, "color": "#4F46E5"},
    "project_quality": {"label": "项目经验质量", "weight": 0.25, "color": "#06D6A0"},
    "format_readability": {"label": "格式与可读性", "weight": 0.15, "color": "#FF8C42"},
    "education": {"label": "教育背景", "weight": 0.15, "color": "#FF5E7A"},
    "expression": {"label": "内容表达", "weight": 0.15, "color": "#9B59B6"},
}

LLM_CONFIGS = {
    "deepseek": {
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "label": "DeepSeek",
    },
    # 后续可添加
    # "qwen": { ... },
    # "gpt": { ... },
}
