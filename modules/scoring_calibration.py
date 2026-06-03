"""评分校准实验 — AI 评分 vs 规则基线评分对比

从 Kaggle 数据集中选取 20 份简历（覆盖多个岗位类别），
每份用 Multi-shot（N=3）评估，同时用规则基线打分，
对比分析 AI 评分的合理性。
"""
import json
import os
import sys
import random
import re
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CALIBRATION_CACHE = os.path.join(DATA_DIR, "calibration_cache.json")

# ── 行为锚定动词（用于表达评分） ──
ACTION_VERBS = [
    "developed", "implemented", "designed", "built", "created", "managed",
    "led", "delivered", "optimized", "improved", "increased", "reduced",
    "achieved", "generated", "established", "spearheaded", "architected",
    "engineered", "deployed", "integrated", "migrated", "automated",
    "configured", "coordinated", "facilitated", "mentored", "trained",
]

QUANTIFICATION_WORDS = [
    "%", "percent", "million", "billion", "thousand", "users", "clients",
    "revenue", "cost", "efficiency", "growth", "increase", "decrease",
    "improvement", "reduction", "roi", "kpi", "sla",
]

# 岗位典型技能集
CATEGORY_SKILLS = {
    "Java Developer": ["java", "spring", "hibernate", "j2ee", "maven", "junit", "microservices", "rest", "sql", "tomcat"],
    "Python Developer": ["python", "django", "flask", "pandas", "numpy", "fastapi", "sql", "docker"],
    "Data Science": ["python", "machine learning", "deep learning", "tensorflow", "pytorch", "sql", "pandas", "statistics", "nlp", "visualization"],
    "DevOps Engineer": ["docker", "kubernetes", "jenkins", "git", "ci/cd", "ansible", "terraform", "linux", "aws", "monitoring"],
    "Web Designing": ["html", "css", "javascript", "responsive", "ui/ux", "photoshop", "figma", "wordpress"],
    "Testing": ["testing", "selenium", "junit", "testng", "automation", "manual testing", "api testing", "load testing"],
    "Database": ["sql", "mysql", "oracle", "mongodb", "nosql", "database design", "etl", "data modeling"],
    "Sales": ["sales", "crm", "negotiation", "account management", "forecasting", "presentation"],
    "HR": ["recruitment", "onboarding", "payroll", "employee relations", "hr policies", "performance management"],
    "Blockchain": ["blockchain", "ethereum", "solidity", "web3", "smart contract", "cryptocurrency", "hyperledger"],
}


def extract_skills_found(resume_text: str, category: str) -> list:
    """提取简历中匹配岗位典型技能的技能"""
    text_lower = resume_text.lower()
    skills = CATEGORY_SKILLS.get(category, [])
    if not skills:
        # fallback: 通用技能
        skills = ["python", "java", "sql", "javascript", "html", "css", "git", "docker", "aws", "linux"]
    return [s for s in skills if s in text_lower]


def rule_based_score(resume_text: str, category: str) -> dict:
    """规则基线评分（作为人工评分的近似替代）"""
    text_lower = resume_text.lower()
    words = re.findall(r'\w+', text_lower)
    word_count = len(words)
    char_count = len(resume_text)

    # 技能匹配度: 匹配的技能数 / 该岗位应有技能数
    skills_found = extract_skills_found(resume_text, category)
    total_skills = len(CATEGORY_SKILLS.get(category, []))
    if total_skills == 0:
        total_skills = 10  # fallback
    skills_match = min(100, int(len(skills_found) / total_skills * 100 + 20))

    # 项目经验质量: 量化数据 + 项目数量 + 技术栈
    has_numbers = len(re.findall(r'\d+%|\d+x|\d+ million|\d+ billion|\d+k', text_lower))
    has_projects = len(re.findall(r'project|system|platform|application|tool', text_lower))
    has_tech_stack = len(re.findall(r'technolog|stack|using|built with|developed in', text_lower))
    project_quality = min(100, has_numbers * 15 + has_projects * 8 + has_tech_stack * 10 + 20)

    # 格式与可读性: 长度 + 结构 + 分段
    has_sections = sum(1 for s in ['education', 'experience', 'skills', 'project', 'certification']
                       if s in text_lower)
    length_score = 40 if 500 < char_count < 5000 else (20 if 200 < char_count < 10000 else 10)
    format_readability = min(100, has_sections * 12 + length_score + 10)
    if format_readability < 20:
        format_readability = 20

    # 教育背景: 关键词匹配
    edu_scores = 0
    if re.search(r'phd|doctor|博士', text_lower): edu_scores = 95
    elif re.search(r'master|ms |m\.s\.|硕士', text_lower): edu_scores = 80
    elif re.search(r'bachelor|bs |b\.s\.|本科|b\.tech', text_lower): edu_scores = 65
    elif re.search(r'college|university|大学|学院', text_lower): edu_scores = 50
    else: edu_scores = 30

    # 内容表达: action verbs + 量化 + 语言质量
    action_count = sum(1 for v in ACTION_VERBS if v in text_lower)
    quant_count = sum(1 for q in QUANTIFICATION_WORDS if q in text_lower)
    avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
    expression = min(100, action_count * 5 + quant_count * 8 + 20)
    if avg_word_len > 5.5:
        expression += 10  # 用词更正式
    expression = min(100, expression)

    # 综合分: 加权
    weights = {"skills_match": 0.30, "project_quality": 0.25,
               "format_readability": 0.15, "education": 0.15, "expression": 0.15}
    overall = (skills_match * weights["skills_match"] +
               project_quality * weights["project_quality"] +
               format_readability * weights["format_readability"] +
               edu_scores * weights["education"] +
               expression * weights["expression"])

    return {
        "skills_match": round(skills_match, 0),
        "project_quality": round(project_quality, 0),
        "format_readability": round(format_readability, 0),
        "education": round(edu_scores, 0),
        "expression": round(expression, 0),
        "overall": round(overall, 0),
        "details": {
            "skills_found": skills_found,
            "skill_ratio": f"{len(skills_found)}/{len(CATEGORY_SKILLS.get(category, []))}",
            "has_numbers": has_numbers,
            "has_sections": has_sections,
            "action_verbs": action_count,
            "quantifications": quant_count,
            "word_count": word_count,
        }
    }


def run_calibration(n_resumes: int = 20):
    """运行校准实验: 选简历 → AI评分 → 规则评分 → 对比"""
    import pandas as pd
    from modules.knowledge_base import ResumeKnowledgeBase
    from modules.resume_evaluator import ResumeEvaluator

    kb = ResumeKnowledgeBase()
    evaluator = ResumeEvaluator()

    if kb.kaggle_df is None:
        return {"error": "Kaggle data not loaded"}

    df = kb.kaggle_df
    categories = df["Category"].unique().tolist()

    # 从每个类别选几份，尽量覆盖多样本
    random.seed(42)
    selected = []
    n_per_cat = max(1, n_resumes // len(categories))
    for cat in categories:
        subset = df[df["Category"] == cat]
        n = min(n_per_cat, len(subset))
        if n > 0:
            sampled = subset.sample(n=n, random_state=random.randint(1, 100))
            for _, row in sampled.iterrows():
                selected.append((cat, row["Resume"]))

    # 如果还不够，随机补
    if len(selected) < n_resumes:
        extra = df.sample(n=n_resumes - len(selected), random_state=99)
        for _, row in extra.iterrows():
            selected.append((row["Category"], row["Resume"]))

    selected = selected[:n_resumes]

    print(f"选取 {len(selected)} 份简历进行校准实验...")

    results = []
    for i, (cat, resume_text) in enumerate(selected):
        resume_short = resume_text[:3000]
        print(f"  [{i+1}/{len(selected)}] {cat}...", end=" ")

        # AI 评分（Multi-shot）
        try:
            ai_result = evaluator.evaluate(resume_short, cat, n_samples=3)
        except Exception as e:
            print(f"AI评分失败: {e}")
            continue

        # 规则基线评分
        rule_result = rule_based_score(resume_text, cat)

        # 提取维度对比
        dims_ai = {}
        for d in ai_result.get("dimensions", []):
            dims_ai[d["key"]] = {
                "score": d["score"],
                "ci": d["ci"],
                "ci_low": d["ci_low"],
                "ci_high": d["ci_high"],
            }

        result = {
            "category": cat,
            "resume_preview": resume_text[:150],
            "ai_overall": ai_result.get("overall", 0),
            "ai_overall_ci": ai_result.get("overall_ci", 0),
            "rule_overall": rule_result["overall"],
            "overall_diff": abs(ai_result.get("overall", 0) - rule_result["overall"]),
            "ai_dimensions": dims_ai,
            "rule_dimensions": {k: rule_result[k] for k in ["skills_match", "project_quality",
                                                              "format_readability", "education", "expression"]},
            "rule_details": rule_result["details"],
        }
        results.append(result)
        print(f"AI={result['ai_overall']}  规则={result['rule_overall']}  diff={result['overall_diff']}")
        time.sleep(0.5)  # 避免 API 限流

    # 汇总统计
    diffs = [r["overall_diff"] for r in results]
    ai_overalls = [r["ai_overall"] for r in results]
    rule_overalls = [r["rule_overall"] for r in results]

    summary = {
        "n_samples": len(results),
        "mean_diff": round(sum(diffs) / len(diffs), 1) if diffs else 0,
        "max_diff": max(diffs) if diffs else 0,
        "min_diff": min(diffs) if diffs else 0,
        "ai_mean": round(sum(ai_overalls) / len(ai_overalls), 1) if ai_overalls else 0,
        "rule_mean": round(sum(rule_overalls) / len(rule_overalls), 1) if rule_overalls else 0,
        "samples": results,
    }

    return summary


def save_calibration(n_resumes: int = 20):
    print(f"=== 评分校准实验 (n={n_resumes}) ===")
    result = run_calibration(n_resumes)
    with open(CALIBRATION_CACHE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n校准完成！共 {result.get('n_samples', 0)} 份，平均差值 {result.get('mean_diff', '-')}")
    print(f"缓存已保存到 {CALIBRATION_CACHE}")
    return result


def load_calibration() -> dict:
    if os.path.exists(CALIBRATION_CACHE):
        with open(CALIBRATION_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


if __name__ == "__main__":
    save_calibration(n_resumes=20)
