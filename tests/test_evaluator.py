"""评估引擎单元测试"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.resume_evaluator import ResumeEvaluator


def test_evaluator_loads():
    """测试评估器能正常加载"""
    ev = ResumeEvaluator()
    assert ev is not None
    assert "deepseek" in ev.models


def test_aggregate_single_sample():
    """测试单次评分聚合逻辑"""
    ev = ResumeEvaluator()
    results = [{
        "scores": {"skills_match": 75, "project_quality": 70,
                   "format_readability": 80, "education": 85, "expression": 72},
        "overall": 76,
        "strengths": ["技能全面"],
        "weaknesses": ["量化不足"],
        "suggestions": ["增加数据"],
        "summary": "良好",
    }]
    agg = ev._aggregate(results, n_samples=1)
    assert agg["overall"] == 76
    assert len(agg["dimensions"]) == 5
    assert agg["n_samples"] == 1
    assert agg["overall_ci"] == 0.0  # 单次没有 CI


def test_aggregate_multi_sample():
    """测试多次评分聚合（含 CI 计算）"""
    ev = ResumeEvaluator()
    results = [
        {"scores": {"skills_match": 75, "project_quality": 70,
                    "format_readability": 80, "education": 85, "expression": 72},
         "overall": 76},
        {"scores": {"skills_match": 78, "project_quality": 72,
                    "format_readability": 82, "education": 84, "expression": 70},
         "overall": 78},
        {"scores": {"skills_match": 72, "project_quality": 68,
                    "format_readability": 78, "education": 86, "expression": 74},
         "overall": 75},
    ]
    agg = ev._aggregate(results, n_samples=3)
    assert agg["n_samples"] == 3
    assert agg["overall_ci"] > 0  # 多次应该有 CI
    assert agg["overall_ci_low"] < agg["overall"] < agg["overall_ci_high"]
    # 每个维度都应该有 CI
    for d in agg["dimensions"]:
        assert d["ci"] >= 0
        assert d["ci_low"] <= d["score"] <= d["ci_high"]


def test_aggregate_with_errors():
    """测试部分结果有错误时的容错"""
    ev = ResumeEvaluator()
    results = [
        {"scores": {"skills_match": 75, "project_quality": 70,
                    "format_readability": 80, "education": 85, "expression": 72},
         "overall": 76},
        {"error": "API 错误", "raw": "..."},
    ]
    agg = ev._aggregate(results, n_samples=2)
    assert "error" not in agg  # 有有效结果就不应该返回 error
    assert agg["overall"] == 76  # 只用有效结果


def test_dimension_weights():
    """测试验证权重配置完整性"""
    from utils.config import EVAL_WEIGHTS
    total_weight = sum(cfg["weight"] for cfg in EVAL_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 0.001  # 权重之和应等于 1
    assert len(EVAL_WEIGHTS) == 5  # 5 个维度
    for key in ["skills_match", "project_quality", "format_readability", "education", "expression"]:
        assert key in EVAL_WEIGHTS
        assert "label" in EVAL_WEIGHTS[key]
        assert "weight" in EVAL_WEIGHTS[key]
