"""知识库模块 - 加载 Kaggle 数据集 + 优秀简历库"""
import pandas as pd
import os
import json

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KAGGLE_CSV = os.path.join(DATA_DIR, "UpdatedResumeDataSet.csv")


class ResumeKnowledgeBase:
    def __init__(self):
        self.kaggle_df = None
        self.excellent_resumes = []
        self.excellent_db = None  # ExcellentResumeDB 实例
        self._load_kaggle()
        self._load_excellent()

    def _load_kaggle(self):
        if os.path.exists(KAGGLE_CSV):
            self.kaggle_df = pd.read_csv(KAGGLE_CSV)
            self.kaggle_df["Category"] = self.kaggle_df["Category"].str.strip()
            print(f"[知识库] Kaggle 数据集: {len(self.kaggle_df)} 份简历")

    def _load_excellent(self):
        """加载优秀简历库（优先用采集器的真实数据）"""
        try:
            # 优先用采集器的真实简历数据
            from modules.resume_collector import ResumeCollector
            self.collector = ResumeCollector()
            self.excellent_resumes = self.collector.resumes
            print(f"[知识库] 优秀简历库: {len(self.excellent_resumes)} 份")
        except ImportError:
            self.excellent_resumes = []
            print("[知识库] 优秀简历库未加载")

    @property
    def categories(self) -> list:
        if self.kaggle_df is not None:
            return sorted(self.kaggle_df["Category"].unique().tolist())
        return []

    def get_category_stats(self) -> dict:
        if self.kaggle_df is not None:
            return self.kaggle_df["Category"].value_counts().to_dict()
        return {}

    def get_sample_resumes(self, category: str, n: int = 5) -> list:
        if self.kaggle_df is None:
            return []
        subset = self.kaggle_df[self.kaggle_df["Category"] == category]
        return subset["Resume"].head(n).tolist()

    def get_category_summary(self, category: str) -> str:
        if self.kaggle_df is None:
            return ""
        subset = self.kaggle_df[self.kaggle_df["Category"] == category]
        texts = subset["Resume"].tolist()
        combined = "\n\n---\n\n".join(texts[:5])
        return combined[:5000]

    def get_excellent_examples(self, category: str) -> list:
        """获取某岗位的优秀简历示例"""
        return [r for r in self.excellent_resumes if r.get("category") == category]

    def get_excellent_avg_scores(self, category: str) -> dict:
        """获取某岗位优秀简历的平均分"""
        matched = self.get_excellent_examples(category)
        if not matched:
            return {}
        avg = {}
        for dim in ["skills_match", "project_quality", "format_readability", "education", "expression"]:
            scores = [r.get("eval_scores", {}).get(dim, 0) for r in matched if "eval_scores" in r]
            avg[dim] = round(sum(scores) / len(scores), 1) if scores else 0
        return avg

    def compare_with_excellent(self, resume_text: str, category: str) -> dict:
        """将简历与优秀简历对比，返回差距分析"""
        matched = self.get_excellent_examples(category)
        if not matched:
            return {}
        return {
            "excellent_count": len(matched),
            "avg_scores": self.get_excellent_avg_scores(category),
        }

