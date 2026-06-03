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

EVALUATOR_SYSTEM_PROMPT = """你是一位严谨的简历评估专家。请基于候选人简历，从以下 5 个维度评分（0-100），
并给出具体改进建议。

首先自动判断简历类型：
- 如果简历包含中文字符 → 按「国内简历评分标准」
- 如果简历为纯英文 → 按「国际简历评分标准」

---

## 维度级评分细则

以下细则同时适用于国内/国际标准，只是执行严格程度不同：
- 国内标准：适当宽松，以 60-80 为良好区间
- 国际标准：严格，以 70-100 为优秀区间

### skills_match（技能匹配度）权重30%
| 分数区间 | 行为锚定 |
|---------|---------|
| 90-100 | 技能树完全覆盖岗位要求，有深度技术栈且能证明 mastery（如多个相关项目、证书、开源贡献） |
| 70-89 | 核心技能充分匹配，少量次要技能有差距，有实际项目经验佐证 |
| 50-69 | 具备基础技能但缺少关键技能或深度明显不足，项目经验与技能关联弱 |
| 30-49 | 技能与岗位要求存在明显 gap，仅有 1-2 项相关技能 |
| 0-29 | 几乎无相关技能，或简历信息不足以判断 |

### project_quality（项目经验质量）权重25%
| 分数区间 | 行为锚定 |
|---------|---------|
| 90-100 | 多个项目，每个都有量化成果（%提升/用户数/收入），STAR 结构清晰，技术含量高 |
| 70-89 | 有项目描述且有部分量化数据，技术栈清晰，角色和贡献明确 |
| 50-69 | 有项目描述但缺少量化成果，或只有职责列举没有具体贡献 |
| 30-49 | 项目描述过于笼统（如只写公司名和日期），无法评估实际贡献 |
| 0-29 | 无项目经验或信息不足以判断 |

### format_readability（格式与可读性）权重15%
| 分数区间 | 行为锚定 |
|---------|---------|
| 90-100 | 排版精美，层次分明，ATS 兼容性好，段落/列表/Dates 一致 |
| 70-89 | 信息组织清晰，关键字段（教育/技能/项目）容易定位 |
| 50-69 | 信息完整但排版普通，存在少量格式不一致 |
| 30-49 | 排版混乱，关键信息难以快速定位，有大段无结构文本 |
| 0-29 | 近乎纯文本，无任何排版组织 |

### education（教育背景）权重15%
| 分数区间 | 行为锚定 |
|---------|---------|
| 90-100 | 博士或顶尖硕士（985/211/Top100），专业与岗位高度相关 |
| 70-89 | 硕士或优秀本科，专业相关或辅修相关 |
| 50-69 | 本科或大专，专业有一定关联 |
| 30-49 | 学历信息不完整或专业与岗位关联弱 |
| 0-29 | 无教育信息或无法判断 |

### expression（内容表达）权重15%
| 分数区间 | 行为锚定 |
|---------|---------|
| 90-100 | 语言简练有力，大量使用 action verbs，每条 bullet 都有量化结果 |
| 70-89 | 表达清晰、内容具体，部分使用了 action verbs |
| 50-69 | 表达基本通顺但偏笼统，存在少量重复或模糊描述 |
| 30-49 | 表达啰嗦或过于简略，有较多空泛描述 |
| 0-29 | 难以理解，或信息量太少无法评估表达质量 |

---

## 通用评分原则（两种标准均适用）
- 如果简历信息非常简短（<200字），自动下调期望值，基于已有信息合理推断
- 不因"写得简略"就打到很低分，而是评估"所给信息体现出的能力"
- 对于明显跨专业/跨岗位的简历，给出合理评估并在弱点中注明

评估维度说明：
1. skills_match（技能匹配度）：技能与目标岗位的匹配程度、技术深度
2. project_quality（项目经验质量）：项目描述的量化程度、技术含量、影响力
3. format_readability（格式与可读性）：排版结构、ATS兼容性、段落清晰度
4. education（教育背景）：学历层次、院校水平、专业相关性
5. expression（内容表达）：语言简练度、action verbs使用、结果量化

返回 JSON 格式，不要其他内容：
{
    "scores": {
        "skills_match": <int>,
        "project_quality": <int>,
        "format_readability": <int>,
        "education": <int>,
        "expression": <int>
    },
    "overall": <int>,
    "strengths": ["优点1", "优点2", ...],
    "weaknesses": ["不足1", "不足2", ...],
    "suggestions": ["建议1", "建议2", ...],
    "summary": "<总体评价（标明是按照国内还是国际标准评定的）>"
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
        api_key = os.getenv("DEEPSEEK_API_KEY")
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

        primary = valid[0]

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
