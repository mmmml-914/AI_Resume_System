"""工具函数 & 配置单元测试"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.config import EVAL_WEIGHTS, LLM_CONFIGS


class TestEvalWeights:
    """评估权重配置验证"""

    def test_total_weight_is_one(self):
        total = sum(cfg["weight"] for cfg in EVAL_WEIGHTS.values())
        # 使用 abs 比较浮点数
        assert abs(total - 1.0) < 0.001

    def test_five_dimensions(self):
        assert len(EVAL_WEIGHTS) == 5

    def test_required_keys(self):
        required = {"skills_match", "project_quality", "format_readability", "education", "expression"}
        assert set(EVAL_WEIGHTS.keys()) == required

    def test_each_dimension_has_all_fields(self):
        for key, cfg in EVAL_WEIGHTS.items():
            assert "label" in cfg, f"{key} missing label"
            assert "weight" in cfg, f"{key} missing weight"
            assert "color" in cfg, f"{key} missing color"
            assert isinstance(cfg["weight"], (int, float))
            assert 0 < cfg["weight"] < 1

    def test_skills_match_highest_weight(self):
        """技能匹配度权重最高"""
        assert EVAL_WEIGHTS["skills_match"]["weight"] == 0.30

    def test_label_types(self):
        for key, cfg in EVAL_WEIGHTS.items():
            assert isinstance(cfg["label"], str)
            assert len(cfg["label"]) > 0


class TestLLMConfigs:
    """LLM 配置验证"""

    def test_deepseek_configured(self):
        assert "deepseek" in LLM_CONFIGS

    def test_deepseek_has_all_fields(self):
        cfg = LLM_CONFIGS["deepseek"]
        assert "api_key" in cfg
        assert "base_url" in cfg
        assert "model" in cfg

    def test_deepseek_has_label(self):
        assert LLM_CONFIGS["deepseek"]["label"] == "DeepSeek"

    def test_deepseek_default_url(self):
        """默认 base_url 应为 deepseek"""
        url = LLM_CONFIGS["deepseek"].get("base_url") or "https://api.deepseek.com"
        assert "deepseek" in url
