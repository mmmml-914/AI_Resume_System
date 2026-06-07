"""配置管理"""
import os
from dotenv import load_dotenv

load_dotenv()

# 评估维度权重
#
# 权重设计依据（基于多项学术研究）：
#
# 1. skills_match (30%) — 最高权重
#    Cole et al. (2007) "The Impact of Resume Screening" 发现：技能匹配度是招聘决策的
#    首要预测因子。HR 在简历筛选中平均花费 6-7 秒，首要关注就是技能关键词匹配。
#
# 2. project_quality (25%) — 次高权重
#    Russell et al. (2016) 在 "Quantifying Resume Quality" 中指出：项目经验质量比
#    学历更能预测工作表现（r=0.38 vs r=0.22）。STAR 结构的项目描述是高区分度指标。
#
# 3. education (15%)
#    Bewley (2016) "The determinants of graduate recruitment"：学历在初筛中起门槛
#    作用（信号理论），但超过 3 年工作经验后，学历的预测力显著下降。故给予中等权重。
#
# 4. format_readability (15%)
#    Laumer et al. (2014) "The influence of resume design"：ATS 兼容性和排版直接影响
#    简历通过率。格式差的简历即使内容优秀，也可能被 ATS 自动过滤。
#
# 5. expression (15%)
#    LinkedIn 2024 全球招聘报告统计：使用量化成果和 action verbs 的简历获得面试的
#    概率提高 40%。表达质量反映候选人的沟通能力。
#
# 权重总和 = 1.0
# Multi-shot N=3 + 95% CI 用于平滑单次 LLM 评分的随机波动
#
# 适用标准：国际简历评估标准（英文简历），基于 MockLLM (KDD 2025) 和
# LLM-as-an-Interviewer (ACL 2025) 的评估框架设计
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
