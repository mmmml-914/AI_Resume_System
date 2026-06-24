"""简历评估引擎 - 多维度加权评分，多模型对比，支持 Multi-shot 置信区间 + RAG 参考"""
import os
import json
import time
import statistics
from openai import OpenAI
from dotenv import load_dotenv
from utils.config import EVAL_WEIGHTS
from modules.rag_knowledge import build_context_prompt

load_dotenv()

def _get_api_key() -> str:
    """从环境变量或 Streamlit secrets 读取 API Key"""
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("DEEPSEEK_API_KEY", "")
    except ImportError:
        return ""

EVALUATOR_SYSTEM_PROMPT = """You are a professional resume evaluator specializing in international/Western resume standards.
Evaluate the candidate's resume across 5 dimensions (0-100 each) and provide specific improvement suggestions.

All resumes in this system are in English. Apply international evaluation standards consistently.

---

## Dimension Scoring Rubrics

### skills_match（技能匹配度）权重30% — Core technical alignment
| Score Range | Behavioral Anchor |
|-------------|-------------------|
| 90-100 | Skills perfectly match the target role; deep expertise demonstrated through projects, certifications, open-source contributions, or publications; proficiency in niche/advanced tools |
| 70-89 | Core skills well-aligned; minor gaps in secondary skills; solid project evidence supporting claimed expertise |
| 50-69 | Has foundational skills but missing key technologies or lacks depth; project-skill connection is weak |
| 30-49 | Significant skill gaps relative to job requirements; only 1-2 transferable skills |
| 0-29 | Virtually no relevant skills, or insufficient information to assess |

### project_quality（项目经验质量）权重25% — Achievement & impact
| Score Range | Behavioral Anchor |
|-------------|-------------------|
| 90-100 | Multiple projects with quantified outcomes (% improvement, revenue, users, performance metrics); STAR structure; high technical complexity |
| 70-89 | Clear project descriptions with some quantification; technology stack is visible; role and contribution are specific |
| 50-69 | Projects listed but lacking metrics; reads like a job description rather than accomplishments |
| 30-49 | Vague descriptions (company name + dates only); cannot assess actual contribution |
| 0-29 | No project experience or insufficient information |

### education（教育背景）权重15% — Academic credentials
| Score Range | Behavioral Anchor |
|-------------|-------------------|
| 90-100 | PhD or top-tier Master's from globally ranked university (QS/Times Top 100); field directly relevant; high GPA (>3.7/4.0 or equivalent); honors/research publications |
| 70-89 | Master's or strong Bachelor's from recognized university; relevant major or minor; good GPA (>3.3/4.0) |
| 50-69 | Bachelor's degree; field somewhat related; adequate academic standing |
| 30-49 | Education listed but incomplete, or field poorly related to target role |
| 0-29 | No education information available or unverifiable |

### format_readability（格式与可读性）权重15% — ATS optimization & structure
| Score Range | Behavioral Anchor |
|-------------|-------------------|
| 90-100 | Excellent layout, consistent formatting, ATS-friendly section headers; clear hierarchy with bullet points, consistent date formats; fits 1-2 pages |
| 70-89 | Well-organized; key sections (summary/skills/experience/education) easy to locate; minor inconsistencies |
| 50-69 | Complete information but plain formatting; some inconsistency in styling or structure |
| 30-49 | Cluttered layout; important information hard to find; large unstructured text blocks |
| 0-29 | Almost raw text; no organizational structure |

### expression（内容表达）权重15% — Language & communication quality
| Score Range | Behavioral Anchor |
|-------------|-------------------|
| 90-100 | Concise, powerful language; extensive use of action verbs (delivered, led, architected, optimized); every bullet has quantified results; professional English |
| 70-89 | Clear and specific writing; some action verbs used; most bullets have concrete outcomes |
| 50-69 | Understandable but generic; few action verbs; some vague or repetitive descriptions |
| 30-49 | Verbose or overly brief; mostly passive voice; vague phrases without evidence |
| 0-29 | Incomprehensible or far too little content to evaluate communication |

---

## General Evaluation Rules
- If resume text is very short (<200 words), adjust expectations downward reasonably
- Evaluate what IS presented — don't penalize harshly for brevity, but don't inflate either
- For career-switchers, assess transferable skills fairly and note the transition in weaknesses
- Prioritize QUANTIFIED achievements over listed responsibilities

Dimension definitions:
1. skills_match — keyword alignment with target role, technical depth, breadth
2. project_quality — STAR structure, quantified impact, technical complexity
3. education — degree level, institution quality (global rankings), GPA, relevance
4. format_readability — ATS compatibility, layout, consistency, whitespace use
5. expression — action verbs, quantified results, professional tone, English proficiency

Return JSON format ONLY (no extra text):
{
    "scores": {
        "skills_match": <int>,
        "project_quality": <int>,
        "format_readability": <int>,
        "education": <int>,
        "expression": <int>
    },
    "overall": <int>,
    "strengths": ["strength1", "strength2", ...],
    "weaknesses": ["weakness1", "weakness2", ...],
    "suggestions": ["suggestion1", "suggestion2", ...],
    "summary": "<Chinese summary: one-sentence overall assessment, mentioning which standard was used>"
}"""


class LLMClient:
    """统一 LLM 调用接口，支持多模型"""

    def __init__(self, api_key: str, base_url: str, model: str, label: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=1)
        self.model = model
        self.label = label

    def evaluate(self, resume_text: str, category: str = None, rag_context: str = "") -> dict:
        """对一份简历进行评估"""
        user_content = f"目标岗位: {category or '未指定'}\n\n简历内容:\n{resume_text[:5000]}"
        if rag_context:
            user_content += f"\n\n{rag_context}"
        start = time.time()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        elapsed = time.time() - start
        reply = resp.choices[0].message.content

        try:
            result = json.loads(reply)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', reply, re.DOTALL)
            if match:
                result = json.loads(match.group())
            else:
                result = {"error": "解析失败", "raw": reply[:300]}

        result["model"] = self.label
        result["latency"] = round(elapsed, 1)
        return result


class ResumeEvaluator:
    """简历评估器 - 多维度加权 + 多模型对比"""

    def __init__(self):
        self.models = {}
        # 默认加载 DeepSeek
        self._load_default_model()

    def _load_default_model(self):
        api_key = _get_api_key()
        if api_key:
            self.models["deepseek"] = LLMClient(
                api_key=api_key,
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                label="DeepSeek",
            )

    def add_model(self, name: str, client: LLMClient):
        """添加更多模型进行对比评估"""
        self.models[name] = client

    def evaluate(self, resume_text: str, category: str = None,
                 model_names: list = None, n_samples: int = 1) -> dict:
        """
        评估简历，返回加权综合评分
        model_names: 指定使用哪些模型，默认只用 deepseek
        n_samples: >1 时启用 multi-shot，计算均值 + 95% 置信区间
        """
        if model_names is None:
            model_names = ["deepseek"]

        # 构建 RAG 上下文（同类简历参考）
        rag_ctx = build_context_prompt(resume_text, category)
        has_rag = bool(rag_ctx.strip())

        # 收集所有样本（多模型 × 多轮）
        all_raw = []
        for name in model_names:
            if name not in self.models:
                continue
            client = self.models[name]
            for i in range(n_samples):
                result = client.evaluate(resume_text, category, rag_context=rag_ctx)
                all_raw.append(result)

        if not all_raw:
            return {"error": "无可用模型"}

        return self._aggregate(all_raw, n_samples=n_samples, has_rag=has_rag)

    def _aggregate(self, all_results: list, n_samples: int = 1, has_rag: bool = False) -> dict:
        """聚合评分结果。n_samples>1 时计算各维度的均值与 95% 置信区间。"""
        # 过滤错误
        valid = [r for r in all_results if "error" not in r]
        if not valid:
            return all_results[0] if all_results else {"error": "无有效结果"}

        # 按维度收集所有样本的分数
        dim_scores: dict[str, list[float]] = {key: [] for key in EVAL_WEIGHTS}
        for result in valid:
            scores = result.get("scores", {})
            for key in EVAL_WEIGHTS:
                if key in scores:
                    dim_scores[key].append(scores[key])

        # 计算均值、标准差、95% CI
        dim_details = []
        weighted_total = 0.0
        for dim_key, config in EVAL_WEIGHTS.items():
            scores = dim_scores.get(dim_key, [0])
            n = len(scores)
            mean_val = statistics.mean(scores)
            stdev_val = statistics.stdev(scores) if n >= 2 else 0.0
            ci = round(1.96 * stdev_val / (n ** 0.5), 1) if n >= 2 else 0.0

            dim_details.append({
                "key": dim_key,
                "label": config["label"],
                "score": round(mean_val, 0),       # 均值（向下兼容）
                "score_mean": round(mean_val, 1),  # 均值（精确）
                "ci": ci,                           # 95% 置信区间半宽
                "ci_low": max(0, round(mean_val - ci, 0)),
                "ci_high": min(100, round(mean_val + ci, 0)),
                "weight": config["weight"],
                "weighted": round(mean_val * config["weight"], 1),
                "color": config["color"],
                "n_samples": n,
            })
            weighted_total += mean_val * config["weight"]

        weighted_score = weighted_total

        # 总分 CI（基于各样本的 overall 分数）
        overalls = [r.get("overall", 0) for r in valid if r.get("overall")]
        overall_mean = round(weighted_score, 0)
        overall_ci = (
            round(1.96 * statistics.stdev(overalls) / (len(overalls) ** 0.5), 1)
            if len(overalls) >= 2 else 0.0
        )

        primary = valid[0] if valid else {}

        return {
            "overall": overall_mean,
            "overall_ci": overall_ci,
            "overall_ci_low": max(0, overall_mean - overall_ci),
            "overall_ci_high": min(100, overall_mean + overall_ci),
            "weighted_score": round(weighted_score, 1),
            "dimensions": dim_details,
            "rag_used": has_rag,
            "strengths": primary.get("strengths", []),
            "weaknesses": primary.get("weaknesses", []),
            "suggestions": primary.get("suggestions", []),
            "summary": primary.get("summary", ""),
            "model_results": {f"sample_{i}": r for i, r in enumerate(valid)},
            "models_used": ["deepseek"],
            "n_samples": n_samples,
        }

    def evaluate_with_benchmark(self, resume_text: str, category: str,
                                benchmark_resumes: list) -> dict:
        """评估简历并与基准（Kaggle同类简历）对比"""
        result = self.evaluate(resume_text, category)

        # 基准分析：用 LLM 判断简历在同类中的水平
        if benchmark_resumes:
            client = self.models.get("deepseek")
            if client:
                benchmark_sample = benchmark_resumes[0][:2000]
                comparison = client.client.chat.completions.create(
                    model=client.model,
                    messages=[{
                        "role": "system",
                        "content": "你是一位简历分析专家。比较两份简历，给出简短的对比分析（50字以内）。"
                    }, {
                        "role": "user",
                        "content": f"目标岗位: {category}\n\n简历A(待评估):\n{resume_text[:1500]}\n\n简历B(同类参考):\n{benchmark_sample}"
                    }],
                    temperature=0.3,
                    max_tokens=300,
                )
                result["benchmark_comparison"] = comparison.choices[0].message.content

        return result
