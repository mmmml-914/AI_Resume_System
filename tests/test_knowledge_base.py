"""知识库单元测试 — ResumeKnowledgeBase"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pandas as pd
from unittest.mock import MagicMock, patch, PropertyMock
from modules.knowledge_base import ResumeKnowledgeBase


SAMPLE_KAGGLE_DF = pd.DataFrame({
    "Category": ["Data Science", "Data Science", "ML Engineer", "ML Engineer", "Data Analyst"],
    "Resume": [
        "Python SQL ML TensorFlow",
        "Python R Statistics Tableau",
        "Python PyTorch Docker K8s",
        "Java Python Spark Hadoop",
        "SQL Excel Tableau Python",
    ],
})


class TestKnowledgeBaseLoad:
    """数据加载测试"""

    def test_load_kaggle_success(self):
        """手动构造后验证 categories"""
        kb = ResumeKnowledgeBase()
        # 注入 mock df
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        assert len(kb.kaggle_df) == 5
        assert kb.kaggle_df["Category"].nunique() == 3

    def test_categories_property(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        cats = kb.categories
        assert cats == ["Data Analyst", "Data Science", "ML Engineer"]

    def test_categories_empty(self):
        kb = ResumeKnowledgeBase()
        assert kb.categories == []

    def test_categories_none(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = None
        assert kb.categories == []


class TestKnowledgeBaseStats:
    """统计方法测试"""

    def test_get_category_stats(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        stats = kb.get_category_stats()
        assert stats["Data Science"] == 2
        assert stats["ML Engineer"] == 2
        assert stats["Data Analyst"] == 1

    def test_get_category_stats_no_data(self):
        kb = ResumeKnowledgeBase()
        assert kb.get_category_stats() == {}

    def test_get_category_stats_none(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = None
        assert kb.get_category_stats() == {}


class TestKnowledgeBaseSamples:
    """样本查询测试"""

    def test_get_sample_resumes(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        samples = kb.get_sample_resumes("Data Science", n=2)
        assert len(samples) == 2
        assert "Python" in samples[0]

    def test_get_sample_resumes_limit(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        samples = kb.get_sample_resumes("Data Science", n=1)
        assert len(samples) == 1

    def test_get_sample_resumes_no_data(self):
        kb = ResumeKnowledgeBase()
        assert kb.get_sample_resumes("ML", n=3) == []

    def test_get_sample_resumes_nonexistent_category(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        samples = kb.get_sample_resumes("Biology", n=3)
        assert samples == []

    def test_get_sample_resumes_exceeds_available(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        samples = kb.get_sample_resumes("Data Science", n=99)
        assert len(samples) == 2  # only 2 available


class TestKnowledgeBaseSummary:
    """摘要方法测试"""

    def test_get_category_summary(self):
        kb = ResumeKnowledgeBase()
        kb.kaggle_df = SAMPLE_KAGGLE_DF
        summary = kb.get_category_summary("Data Science")
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_category_summary_no_data(self):
        kb = ResumeKnowledgeBase()
        assert kb.get_category_summary("ML") == ""

    def test_get_category_summary_max_length(self):
        """验证截断到 5000 字符"""
        kb = ResumeKnowledgeBase()
        # 制造超长文本
        long_df = pd.DataFrame({
            "Category": ["Test"],
            "Resume": ["X" * 6000],
        })
        kb.kaggle_df = long_df
        summary = kb.get_category_summary("Test")
        assert len(summary) <= 5000


class TestKnowledgeBaseExcellent:
    """优秀简历库测试"""

    def test_get_excellent_examples(self):
        kb = ResumeKnowledgeBase()
        kb.excellent_resumes = [
            {"category": "Data Science", "title": "DS 1"},
            {"category": "ML Engineer", "title": "ML 1"},
            {"category": "Data Science", "title": "DS 2"},
        ]
        ds_examples = kb.get_excellent_examples("Data Science")
        assert len(ds_examples) == 2
        assert ds_examples[0]["title"] == "DS 1"

    def test_get_excellent_examples_empty(self):
        kb = ResumeKnowledgeBase()
        assert kb.get_excellent_examples("Data Science") == []

    def test_get_excellent_examples_no_match(self):
        kb = ResumeKnowledgeBase()
        kb.excellent_resumes = [{"category": "Data Science", "title": "DS 1"}]
        assert kb.get_excellent_examples("Biology") == []

    def test_get_excellent_avg_scores(self):
        kb = ResumeKnowledgeBase()
        kb.excellent_resumes = [
            {"category": "Data Science", "eval_scores": {
                "skills_match": 85, "project_quality": 90,
                "format_readability": 80, "education": 85, "expression": 88,
            }},
            {"category": "Data Science", "eval_scores": {
                "skills_match": 75, "project_quality": 80,
                "format_readability": 82, "education": 80, "expression": 78,
            }},
        ]
        avg = kb.get_excellent_avg_scores("Data Science")
        assert avg["skills_match"] == 80.0
        assert avg["project_quality"] == 85.0

    def test_get_excellent_avg_no_data(self):
        kb = ResumeKnowledgeBase()
        assert kb.get_excellent_avg_scores("Data Science") == {}

    def test_compare_with_excellent(self):
        kb = ResumeKnowledgeBase()
        kb.excellent_resumes = [
            {"category": "ML", "eval_scores": {
                "skills_match": 90, "project_quality": 85,
                "format_readability": 80, "education": 88, "expression": 82,
            }},
        ]
        result = kb.compare_with_excellent("some resume text", "ML")
        assert result["excellent_count"] == 1
        assert "avg_scores" in result

    def test_compare_with_excellent_no_match(self):
        kb = ResumeKnowledgeBase()
        kb.excellent_resumes = [{"category": "ML", "eval_scores": {}}]
        result = kb.compare_with_excellent("text", "Data Science")
        assert result == {}
