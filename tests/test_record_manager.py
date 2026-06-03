"""面试/评估记录管理器单元测试 — RecordsManager"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from modules.record_manager import RecordsManager


class TestRecordManagerCRUD:
    """基本 CRUD 操作"""

    def test_add_record(self):
        mgr = RecordsManager()
        rid = mgr.add_record({"category": "Data Science", "scores": {"overall": 85}})
        assert rid is not None
        assert len(rid) == 8  # uuid4[:8]
        assert len(mgr._records) == 1

    def test_add_record_adds_timestamp(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "ML"})
        assert "created_at" in mgr._records[0]
        assert "record_id" in mgr._records[0]

    def test_get_records_returns_latest_first(self):
        import time
        mgr = RecordsManager()
        mgr.add_record({"category": "A", "scores": {"overall": 80}})
        time.sleep(1)  # created_at 只有秒级精度，需等待至少 1 秒
        mgr.add_record({"category": "B", "scores": {"overall": 90}})
        records = mgr.get_records(10)
        assert records[0]["category"] == "B"
        assert records[1]["category"] == "A"

    def test_get_records_limit(self):
        mgr = RecordsManager()
        for i in range(10):
            mgr.add_record({"category": f"Cat{i}", "scores": {"overall": 70 + i}})
        assert len(mgr.get_records(3)) == 3
        assert len(mgr.get_records(999)) == 10

    def test_get_record_by_id(self):
        mgr = RecordsManager()
        rid = mgr.add_record({"category": "DS", "scores": {"overall": 88}})
        record = mgr.get_record(rid)
        assert record["category"] == "DS"

    def test_get_record_not_found(self):
        mgr = RecordsManager()
        assert mgr.get_record("nonexistent") == {}

    def test_delete_record(self):
        mgr = RecordsManager()
        rid = mgr.add_record({"category": "DS"})
        assert mgr.delete_record(rid) is True
        assert mgr.get_record(rid) == {}

    def test_clear(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "A"})
        mgr.add_record({"category": "B"})
        mgr.clear()
        assert mgr._records == []
        assert mgr.get_stats()["total"] == 0


class TestRecordManagerStats:
    """统计数据测试"""

    def test_stats_empty(self):
        mgr = RecordsManager()
        stats = mgr.get_stats()
        assert stats["total"] == 0
        assert stats["categories"] == {}
        assert stats["avg_scores"] == {}
        assert stats["by_category"] == {}

    def test_stats_basic(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "DS", "scores": {"overall": 80}})
        mgr.add_record({"category": "DS", "scores": {"overall": 90}})
        stats = mgr.get_stats()
        assert stats["total"] == 2
        assert stats["categories"]["DS"] == 2
        assert stats["avg_scores"]["overall"] == 85.0

    def test_stats_multiple_categories(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "DS", "scores": {"overall": 80}})
        mgr.add_record({"category": "ML", "scores": {"overall": 90}})
        mgr.add_record({"category": "DS", "scores": {"overall": 85}})
        stats = mgr.get_stats()
        assert stats["categories"]["DS"] == 2
        assert stats["categories"]["ML"] == 1
        assert stats["by_category"]["DS"]["avg_overall"] == 82.5
        assert stats["by_category"]["ML"]["avg_overall"] == 90.0

    def test_stats_dimension_scores(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "DS", "scores": {
            "overall": 80, "skills_match": 85, "project_quality": 75,
        }})
        stats = mgr.get_stats()
        assert stats["avg_scores"]["skills_match"] == 85.0
        assert stats["avg_scores"]["project_quality"] == 75.0

    def test_stats_no_scores(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "DS"})
        stats = mgr.get_stats()
        assert stats["total"] == 1
        assert stats["avg_scores"] == {}


class TestRecordManagerDimensionStats:
    """维度统计测试"""

    def test_dimension_stats_empty(self):
        mgr = RecordsManager()
        assert mgr.get_dimension_stats() == []

    def test_dimension_stats_basic(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "DS", "scores": {
            "skills_match": 80, "project_quality": 70,
            "format_readability": 90, "education": 85, "expression": 75,
        }})
        dims = mgr.get_dimension_stats()
        assert len(dims) == 5
        dim_map = {d["key"]: d for d in dims}
        assert dim_map["skills_match"]["avg"] == 80.0
        assert dim_map["project_quality"]["avg"] == 70.0
        assert dim_map["education"]["avg"] == 85.0

    def test_dimension_stats_partial(self):
        """只有部分维度数据"""
        mgr = RecordsManager()
        mgr.add_record({"category": "DS", "scores": {"skills_match": 88}})
        dims = mgr.get_dimension_stats()
        assert len(dims) == 1
        assert dims[0]["key"] == "skills_match"
        assert dims[0]["avg"] == 88.0


class TestRecordManagerPersistence:
    """持久化测试"""

    def test_get_all(self):
        mgr = RecordsManager()
        mgr.add_record({"category": "A"})
        mgr.add_record({"category": "B"})
        all_records = mgr.get_all()
        assert len(all_records) == 2

    def test_load_all(self):
        mgr = RecordsManager()
        mgr._records = []
        data = [
            {"category": "A", "scores": {"overall": 80}},
            {"category": "B", "scores": {"overall": 90}},
        ]
        mgr.load_all(data)
        assert len(mgr._records) == 2
        assert mgr._records[0]["category"] == "A"
