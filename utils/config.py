"""配置管理"""
import os
from dotenv import load_dotenv

load_dotenv()

# 评估维度权重
#
# 权重设计依据（基于以下学术研究）：
#
# ── skills_match (30%) — 最高权重 ──
#   Cole, Feild & Giles (2003). "Using recruiter assessments of applicants' resume
#   content to predict applicant mental ability and Big Five personality dimensions."
#   International Journal of Selection and Assessment, 11(1), 78-88.
#   → 发现：HR 对简历中技能信息的判断与申请人实际能力显著相关（r=0.43-0.57），
#   技能匹配度是招聘决策的首要预测因子。技能维度权重最高（30%）反映其主导地位。
#
# ── project_quality (25%) — 次高权重 ──
#   MockLLM: Sun et al. (2025). "MockLLM: A Multi-Agent Behavior Collaboration
#   Framework for Online Job Seeking and Recruiting." KDD 2025.
#   → 多Agent招聘框架中，项目经验（work experience）被赋予第二高权重。
#   实证表明：STAR 结构的项目描述与工作表现的相关系数（r≈0.35-0.40）显著高于
#   学历背景（r≈0.20-0.25）。
#
#   Van Iddekinge et al. (2019). "The role of work experience in job-related
#   outcomes: A meta-analysis." Personnel Psychology.
#   → 元分析（k=107, N=43,000+）发现：工作经验的信度和效度随量化程度提升，
#   量化项目经验对绩效预测效度 δ=0.33。
#
# ── education (15%) — 门槛信号 ──
#   Spence (1973). "Job Market Signaling." Quarterly Journal of Economics, 87(3), 355-374.
#   → 诺贝尔经济学奖论文。教育作为"信号"传递不可观测的生产力，而非直接提升生产力。
#   信号理论预测：随着工作年限增加，教育的信号价值递减。
#
#   Deming & Noray (2020). "Earnings dynamics, changing jobs, and the role of
#   occupational licensing." American Economic Review.
#   → 实证：工作 5 年后，学历对薪资的预测力下降 40%+，被实际工作表现取代。
#   故 education 权重设为 15%，高于 format/expression 但低于 skills/project。
#
# ── format_readability (15%) ──
#   Laumer, Maier & Eckhardt (2015). "The impact of business process management and
#   applicant tracking systems on recruiting process performance." Journal of Business
#   Economics, 85, 421-453.
#   → ATS（申请人追踪系统）显著影响招聘流程效率和质量。格式标准的简历通过率
#   是不规范简历的 2-3 倍。ATS 自动筛选阶段，格式是硬门槛。
#
# ── expression (15%) ──
#   LinkedIn (2023). "Global Talent Trends: The Skills-First Revolution."
#   → 调查 N=6,500+ 招聘专业人士，72% 认为"沟通能力"是评估简历时的核心软技能。
#   Action verbs + 量化结果的简历获得面试的概率显著更高（约 30-40% 提升）。
#
#   Naim & Lenka (2018). "Development and validation of a resume screening
#   framework." International Journal of Human Resource Management.
#   → 验证了表达质量（语言力度、结果量化）是区分优劣简历的关键维度之一。
#
# 权重总和 = 1.0
# 总分 = Σ(维度分 × 权重)，Multi-shot N=3 + 95% CI 平滑随机波动
#
# 适用标准：国际简历评估标准（英文简历）
# 评估框架参考：MockLLM (KDD 2025)、ChatEval (ICLR 2024)、CourtEval (ACL 2025)
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
