"""数据分析模块 — 对 Kaggle 数据集做技能提取、统计分析"""
import os
import json
import re
import pandas as pd
from collections import Counter

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KAGGLE_CSV = os.path.join(DATA_DIR, "UpdatedResumeDataSet.csv")
ANALYSIS_CACHE = os.path.join(DATA_DIR, "analysis_cache.json")

# 常见技能关键词表
SKILL_KEYWORDS = {
    "Python": ["python", "django", "flask", "pandas", "numpy", "scikit", "tensorflow", "pytorch", "keras", "fastapi"],
    "Java": ["java", "spring", "springboot", "hibernate", "mybatis", "jvm", "maven", "gradle", "tomcat"],
    "JavaScript": ["javascript", "js", "node", "react", "vue", "angular", "typescript", "jquery", "express"],
    "SQL": ["sql", "mysql", "postgresql", "oracle", "mongodb", "nosql", "sqlserver", "redis", "database"],
    "DevOps": ["docker", "kubernetes", "k8s", "jenkins", "gitlab", "ansible", "terraform", "ci/cd", "linux"],
    "Cloud": ["aws", "azure", "gcp", "cloud", "s3", "ec2", "lambda"],
    "BigData": ["hadoop", "spark", "kafka", "hive", "flink", "scala", "etl", "data warehouse", "pyspark"],
    "ML/AI": ["machine learning", "deep learning", "nlp", "computer vision", "llm", "gpt", "transformer", "neural network"],
    "Web": ["html", "css", "html5", "css3", "restful", "api", "graphql", "microservice"],
    "Testing": ["testing", "junit", "selenium", "pytest", "mock", "tdd", "qa", "automation"],
    "Tools": ["git", "github", "jira", "confluence", "postman", "swagger", "linux", "bash", "powershell"],
}

# 高频通用词（排除干扰）
STOP_WORDS = {"the", "and", "for", "with", "this", "that", "from", "have", "been", "were",
              "will", "also", "has", "are", "was", "been", "being", "had", "more", "than",
              "very", "just", "about", "over", "such", "each", "into", "than", "then",
              "level", "responsible", "including", "working", "experience", "work", "team"}


def extract_skills(text: str) -> list:
    """从简历文本中提取技能关键词"""
    text_lower = text.lower()
    found = []
    for skill, keywords in SKILL_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(skill)
                break
    return found


def extract_word_freq(texts: list, top_n: int = 100) -> list:
    """提取词频统计"""
    words = []
    for t in texts:
        # 只保留字母
        tokens = re.findall(r'[a-zA-Z]+', t.lower())
        words.extend([w for w in tokens if len(w) > 2 and w not in STOP_WORDS])
    most_common = Counter(words).most_common(top_n)
    return [{"word": w, "count": c} for w, c in most_common]


def run_full_analysis() -> dict:
    """对 Kaggle 数据集运行完整分析，返回结构化结果"""
    if not os.path.exists(KAGGLE_CSV):
        return {"error": "Kaggle CSV not found"}

    df = pd.read_csv(KAGGLE_CSV)
    df["Category"] = df["Category"].str.strip()

    # 1. 岗位分布统计
    cat_counts = df["Category"].value_counts().to_dict()
    cat_stats = {
        "total": len(df),
        "total_categories": df["Category"].nunique(),
        "categories": {k: v for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])},
    }

    # 2. 文本长度统计（按类别）
    df["text_len"] = df["Resume"].str.len()
    text_stats = {
        "overall_avg": int(df["text_len"].mean()),
        "overall_max": int(df["text_len"].max()),
        "overall_min": int(df["text_len"].min()),
        "per_category": {},
    }
    for cat in df["Category"].unique():
        subset = df[df["Category"] == cat]
        text_stats["per_category"][cat] = {
            "avg": int(subset["text_len"].mean()),
            "max": int(subset["text_len"].max()),
            "min": int(subset["text_len"].min()),
            "count": len(subset),
        }

    # 3. 技能提取
    all_skills = []
    skills_per_cat = {}
    for _, row in df.iterrows():
        skills = extract_skills(row["Resume"])
        all_skills.extend(skills)
        cat = row["Category"]
        if cat not in skills_per_cat:
            skills_per_cat[cat] = []
        skills_per_cat[cat].extend(skills)

    skill_stats = {
        "overall": dict(Counter(all_skills).most_common()),
        "per_category": {},
    }
    for cat, skills in skills_per_cat.items():
        skill_stats["per_category"][cat] = dict(Counter(skills).most_common(10))

    # 4. 词频统计（全局 + 每类）
    word_freq = extract_word_freq(df["Resume"].tolist(), top_n=80)
    word_freq_per_cat = {}
    for cat in df["Category"].unique():
        subset = df[df["Category"] == cat]
        word_freq_per_cat[cat] = extract_word_freq(subset["Resume"].tolist(), top_n=30)

    # 5. 教育程度关键词检测（简单统计）
    edu_keywords = {
        "bachelor": ["bachelor", "b.s.", "bs ", "undergraduate", "本科"],
        "master": ["master", "m.s.", "ms ", "graduate", "硕士"],
        "phd": ["phd", "ph.d.", "doctor", "博士", "doctorate"],
        "mba": ["mba"],
    }
    edu_stats = {k: 0 for k in edu_keywords}
    for _, row in df.iterrows():
        text_lower = row["Resume"].lower()
        for edu, kws in edu_keywords.items():
            for kw in kws:
                if kw in text_lower:
                    edu_stats[edu] += 1
                    break

    # 6. 文本复杂度统计（平均单词长度、句子数等）
    complexity = {
        "avg_word_length": round(df["Resume"].apply(lambda x: len(re.findall(r'\w+', x)) / max(len(x), 1) * 100), 1).mean(),
        "avg_word_count": int(df["Resume"].apply(lambda x: len(re.findall(r'\w+', x))).mean()),
    }

    result = {
        "category_stats": cat_stats,
        "text_stats": text_stats,
        "skill_stats": skill_stats,
        "word_freq": word_freq,
        "word_freq_per_category": word_freq_per_cat,
        "education_stats": edu_stats,
        "complexity": complexity,
        "note": "分析基于 Kaggle UpdatedResumeDataSet.csv，962份简历，25个岗位类别",
    }

    return result


def save_analysis():
    """运行分析并缓存到文件"""
    print("开始分析 Kaggle 数据集...")
    result = run_full_analysis()
    with open(ANALYSIS_CACHE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"分析完成！缓存已保存到 {ANALYSIS_CACHE}")
    return result


def load_analysis() -> dict:
    """加载缓存的分析结果"""
    if os.path.exists(ANALYSIS_CACHE):
        with open(ANALYSIS_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


if __name__ == "__main__":
    save_analysis()
