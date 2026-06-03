"""评分验证实验 — 单次 vs Multi-shot 对比"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))

from modules.resume_evaluator import ResumeEvaluator
from modules.knowledge_base import ResumeKnowledgeBase

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
VALIDATION_CACHE = os.path.join(DATA_DIR, "validation_cache.json")


def run_validation(n_resumes: int = 5) -> dict:
    """从不同岗位抽取简历，分别做单次和3次评分，对比波动"""
    kb = ResumeKnowledgeBase()
    evaluator = ResumeEvaluator()

    if kb.kaggle_df is None:
        return {"error": "Kaggle data not loaded"}

    # 从不同类别各取1份
    categories = list(kb.kaggle_df["Category"].unique())
    import random
    random.seed(42)
    sample_cats = random.sample(categories, min(n_resumes, len(categories)))

    results = []
    for cat in sample_cats:
        subset = kb.kaggle_df[kb.kaggle_df["Category"] == cat]
        if len(subset) == 0:
            continue
        resume = subset.iloc[0]["Resume"]
        resume_short = resume[:3000]

        # 单次评分
        single = evaluator.evaluate(resume_short, cat, n_samples=1)
        # 3次评分
        multi = evaluator.evaluate(resume_short, cat, n_samples=3)

        single_overall = single.get("overall", 0)
        multi_overall = multi.get("overall", 0)
        multi_ci = multi.get("overall_ci", 0)

        # 各维度对比
        dim_comparison = []
        for sd, md in zip(single.get("dimensions", []), multi.get("dimensions", [])):
            dim_comparison.append({
                "key": sd["key"],
                "label": sd["label"],
                "single_score": sd["score"],
                "multi_mean": md["score"],
                "multi_ci": md["ci"],
                "ci_low": md["ci_low"],
                "ci_high": md["ci_high"],
            })

        results.append({
            "category": cat,
            "resume_preview": resume[:200],
            "single_overall": single_overall,
            "multi_overall": multi_overall,
            "multi_ci": multi_ci,
            "ci_low": multi.get("overall_ci_low", 0),
            "ci_high": multi.get("overall_ci_high", 0),
            "dimensions": dim_comparison,
        })

        print(f"[{cat}] 单次={single_overall}  3次均值={multi_overall}  CI=+/-{multi_ci}")

    return {
        "samples": results,
        "note": "每份简历使用同一份文本，分别调用 n_samples=1 和 n_samples=3",
        "total_n": len(results),
    }


def save_validation(n_resumes: int = 5):
    print(f"开始评分验证实验 ({n_resumes} 份简历)...")
    result = run_validation(n_resumes)
    with open(VALIDATION_CACHE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"验证完成！缓存已保存到 {VALIDATION_CACHE}")


def load_validation() -> dict:
    if os.path.exists(VALIDATION_CACHE):
        with open(VALIDATION_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


if __name__ == "__main__":
    save_validation(n_resumes=5)
