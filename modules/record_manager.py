"""面试记录管理 — 存储/查询评估和面试记录"""

import os
import json
import time
import uuid

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
RECORDS_FILE = os.path.join(DATA_DIR, "interview_records.json")


class RecordsManager:
    """评估与面试记录管理器"""

    def __init__(self):
        self._records = []
        self._load()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_record(self, record: dict) -> str:
        """添加一条记录，返回 record_id"""
        rid = str(uuid.uuid4())[:8]
        record["record_id"] = rid
        record["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self._records.append(record)
        self._save()
        return rid

    def get_records(self, limit: int = 100) -> list:
        return sorted(self._records, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]

    def get_record(self, record_id: str) -> dict:
        for r in self._records:
            if r.get("record_id") == record_id:
                return r
        return {}

    def delete_record(self, record_id: str) -> bool:
        self._records = [r for r in self._records if r.get("record_id") != record_id]
        self._save()
        return True

    def clear(self):
        self._records = []
        self._save()

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        if not self._records:
            return {"total": 0, "categories": {}, "avg_scores": {}, "by_category": {}}

        categories = {}
        total_scores = {"overall": [], "skills_match": [], "project_quality": [],
                        "format_readability": [], "education": [], "expression": []}
        by_cat = {}

        for r in self._records:
            cat = r.get("category", "未知")
            categories[cat] = categories.get(cat, 0) + 1

            scores = r.get("scores", {})
            if scores.get("overall"):
                total_scores["overall"].append(scores["overall"])
            for dim in ["skills_match", "project_quality", "format_readability", "education", "expression"]:
                if scores.get(dim):
                    total_scores[dim].append(scores[dim])

            if cat not in by_cat:
                by_cat[cat] = {"count": 0, "overall_sum": 0, "overall_list": []}
            by_cat[cat]["count"] += 1
            if scores.get("overall"):
                by_cat[cat]["overall_sum"] += scores["overall"]
                by_cat[cat]["overall_list"].append(scores["overall"])

        avg_scores = {}
        for k, v in total_scores.items():
            if v:
                avg_scores[k] = round(sum(v) / len(v), 1)

        by_category = {}
        for cat, data in by_cat.items():
            by_category[cat] = {
                "count": data["count"],
                "avg_overall": round(data["overall_sum"] / data["count"], 1) if data["count"] else 0,
                "overall_list": data["overall_list"],
            }

        return {
            "total": len(self._records),
            "categories": categories,
            "avg_scores": avg_scores,
            "by_category": by_category,
        }

    def get_dimension_stats(self) -> list:
        """返回各维度平均分列表"""
        if not self._records:
            return []
        dims = ["skills_match", "project_quality", "format_readability", "education", "expression"]
        labels = {"skills_match": "技能匹配度", "project_quality": "项目经验质量",
                  "format_readability": "格式与可读性", "education": "教育背景", "expression": "内容表达"}
        result = []
        for dim in dims:
            scores = [r["scores"][dim] for r in self._records if r.get("scores", {}).get(dim)]
            if scores:
                result.append({
                    "key": dim,
                    "label": labels.get(dim, dim),
                    "avg": round(sum(scores) / len(scores), 1),
                    "min": min(scores),
                    "max": max(scores),
                    "count": len(scores),
                })
        return result

    # ------------------------------------------------------------------
    # 批量导出/导入（用于统一文件持久化）
    # ------------------------------------------------------------------

    def get_all(self) -> list:
        return self._records

    def load_all(self, records: list):
        self._records = records

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self):
        if os.path.exists(RECORDS_FILE):
            try:
                with open(RECORDS_FILE, "r", encoding="utf-8") as f:
                    self._records = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._records = []

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)
