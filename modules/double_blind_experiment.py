"""
双盲实验模块 — 验证 AI 评分的客观性与可靠性

功能：
1. 简历脱敏（去除姓名/邮箱/电话/院校/公司等可识别信息）
2. 层级式人工评分界面（大类 → 细分 → 更细区间，不直接打分）
3. 批量 AI 评分实验（脱敏版 vs 完整版）
4. 人机评分一致性分析（相关系数、Bland-Altman）
"""
import os, json, re, time, random
from datetime import datetime
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KAGGLE_CSV = os.path.join(DATA_DIR, "UpdatedResumeDataSet.csv")
EXPERIMENT_FILE = os.path.join(DATA_DIR, "blind_experiment.json")

# ═══════════════════════════════════════════════
#  层级评分结构
# ═══════════════════════════════════════════════

SCORING_TREE = {
    "优秀 (85-100)": {
        "range": (85, 100),
        "children": {
            "卓越 (95-100)": {
                "range": (95, 100),
                "children": {
                    "接近满分 (98-100)": (98, 100),
                    "表现突出 (95-97)": (95, 97),
                },
            },
            "很好 (85-94)": {
                "range": (85, 94),
                "children": {
                    "扎实全面 (90-94)": (90, 94),
                    "良好以上 (85-89)": (85, 89),
                },
            },
        },
    },
    "良好 (70-84)": {
        "range": (70, 84),
        "children": {
            "中上 (78-84)": {
                "range": (78, 84),
                "children": {
                    "接近优秀 (81-84)": (81, 84),
                    "较好 (78-80)": (78, 80),
                },
            },
            "中等偏上 (70-77)": {
                "range": (70, 77),
                "children": {
                    "尚有亮点 (74-77)": (74, 77),
                    "基本合格 (70-73)": (70, 73),
                },
            },
        },
    },
    "中等 (55-69)": {
        "range": (55, 69),
        "children": {
            "一般 (62-69)": {
                "range": (62, 69),
                "children": {
                    "接近良好 (66-69)": (66, 69),
                    "中规中矩 (62-65)": (62, 65),
                },
            },
            "偏弱 (55-61)": {
                "range": (55, 61),
                "children": {
                    "基础尚可 (58-61)": (58, 61),
                    "需加强 (55-57)": (55, 57),
                },
            },
        },
    },
    "较差 (0-54)": {
        "range": (0, 54),
        "children": {
            "较差 (30-54)": {
                "range": (30, 54),
                "children": {
                    "部分达标 (42-54)": (42, 54),
                    "较多不足 (30-41)": (30, 41),
                },
            },
            "很差 (0-29)": {
                "range": (0, 29),
                "children": {
                    "严重不足 (15-29)": (15, 29),
                    "几乎空白 (0-14)": (0, 14),
                },
            },
        },
    },
}

# 将层级树展平为 {label: (lo, hi)}，用于最终匹配
_FLAT_RANGES = {}

def _flatten(tree, prefix=""):
    for k, v in tree.items():
        label = k.split(" (")[0]  # 去掉区间显示
        if isinstance(v, tuple):
            _FLAT_RANGES[label] = v
        elif isinstance(v, dict):
            r = v.get("range")
            if r:
                _FLAT_RANGES[label] = r
            if "children" in v:
                _flatten(v["children"])

_flatten(SCORING_TREE)


# ═══════════════════════════════════════════════
#  简历脱敏（轻量版 — 仅去掉直接身份信息）
# ═══════════════════════════════════════════════

def anonymize_resume(text: str) -> str:
    """轻量脱敏：仅去除姓名、邮箱、电话、URL，保留院校/公司等评价所需信息"""
    if not text:
        return text

    # 1. 邮箱
    text = re.sub(r'\S+@\S+\.\S+', '[邮箱]', text)

    # 2. 电话（支持多种格式）
    text = re.sub(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', '[电话]', text)

    # 3. URL
    text = re.sub(r'https?://\S+', '[链接]', text)
    text = re.sub(r'www\.\S+', '[链接]', text)

    # 4. LinkedIn
    text = re.sub(r'linkedin\.com/in/\S+', '[领英]', text, flags=re.IGNORECASE)

    # 5. 第一行如果是纯姓名（1-3个单词，无标点）则替换
    lines = text.split('\n')
    for idx in range(min(2, len(lines))):
        stripped = lines[idx].strip()
        if stripped and not any(c in stripped for c in (',', ';', ':', '(', ')', '@', 'http', '.')):
            words = stripped.split()
            if 1 <= len(words) <= 3 and all(w.isalpha() for w in words):
                lines[idx] = '[姓名]'
    text = '\n'.join(lines)

    # 6. 去掉连续3行以上的空行
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    return text


# ═══════════════════════════════════════════════
#  实验数据管理
# ═══════════════════════════════════════════════

def _load_experiments() -> list:
    if not os.path.exists(EXPERIMENT_FILE):
        return []
    with open(EXPERIMENT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_experiments(data: list):
    os.makedirs(os.path.dirname(EXPERIMENT_FILE), exist_ok=True)
    with open(EXPERIMENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_kaggle_csv() -> pd.DataFrame:
    """读取 Kaggle CSV，修复双重编码导致的乱码"""
    if not os.path.exists(KAGGLE_CSV):
        return pd.DataFrame()
    with open(KAGGLE_CSV, 'rb') as f:
        raw = f.read()
    # 双重编码修复：UTF-8 字节被当作 Latin-1 重新编码
    try:
        text = raw.decode('utf-8')
        fixed = text.encode('latin-1').decode('utf-8')
    except Exception:
        fixed = raw.decode('utf-8', errors='replace')
    import io
    return pd.read_csv(io.StringIO(fixed))


def _get_random_resumes(n: int = 1, exclude_ids: set = None, categories: list = None) -> list:
    """从 Kaggle 数据集中随机抽取 n 份简历，可按类别筛选"""
    df = _read_kaggle_csv()
    if categories:
        df = df[df["Category"].isin(categories)]
    if exclude_ids:
        df = df[~df.index.isin(exclude_ids)]
    if len(df) == 0:
        return []
    sampled = df.sample(n=min(n, len(df)))
    results = []
    for idx, row in sampled.iterrows():
        results.append({
            "id": int(idx),
            "category": row["Category"],
            "resume_text": row["Resume"],
        })
    return results


# ═══════════════════════════════════════════════
#  一致性分析
# ═══════════════════════════════════════════════

def compute_agreement(human_scores: list, ai_scores: list) -> dict:
    """计算人机评分一致性"""
    if len(human_scores) < 2:
        return {"error": "样本量不足，至少需要 2 个样本"}
    n = min(len(human_scores), len(ai_scores))
    h = human_scores[:n]
    a = ai_scores[:n]

    import statistics
    diff = [h[i] - a[i] for i in range(n)]
    mean_diff = statistics.mean(diff)
    std_diff = statistics.stdev(diff) if n > 1 else 0

    # Pearson 相关系数
    try:
        from scipy import stats as sp_stats
        r, p_value = sp_stats.pearsonr(h, a)
    except ImportError:
        # 手动计算
        h_mean = statistics.mean(h)
        a_mean = statistics.mean(a)
        num = sum((h[i] - h_mean) * (a[i] - a_mean) for i in range(n))
        den = (sum((h[i] - h_mean)**2 for i in range(n)) *
               sum((a[i] - a_mean)**2 for i in range(n))) ** 0.5
        r = num / den if den != 0 else 0
        p_value = None

    # 平均绝对误差
    mae = sum(abs(d) for d in diff) / n

    return {
        "n": n,
        "pearson_r": round(r, 4),
        "p_value": round(p_value, 4) if p_value else None,
        "mean_diff": round(mean_diff, 2),
        "std_diff": round(std_diff, 2),
        "mae": round(mae, 2),
        "human_mean": round(statistics.mean(h), 1),
        "ai_mean": round(statistics.mean(a), 1),
    }


def get_experiment_stats(experiments: list) -> dict:
    """汇总所有实验的统计"""
    if not experiments:
        return {}

    human_midpoints = []
    ai_blind_midpoints = []
    ai_full_midpoints = []

    for exp in experiments:
        hs = exp.get("human_score", {})
        if hs.get("midpoint"):
            human_midpoints.append(hs["midpoint"])
        if exp.get("ai_score_blind") and exp["ai_score_blind"].get("overall"):
            ai_blind_midpoints.append(exp["ai_score_blind"]["overall"])
        if exp.get("ai_score_full") and exp["ai_score_full"].get("overall"):
            ai_full_midpoints.append(exp["ai_score_full"]["overall"])

    stats = {
        "total": len(experiments),
        "human_count": len(human_midpoints),
        "ai_blind_count": len(ai_blind_midpoints),
        "ai_full_count": len(ai_full_midpoints),
    }

    if human_midpoints and ai_blind_midpoints:
        stats["human_vs_blind"] = compute_agreement(human_midpoints, ai_blind_midpoints)
    if human_midpoints and ai_full_midpoints:
        stats["human_vs_full"] = compute_agreement(human_midpoints, ai_full_midpoints)
    if ai_blind_midpoints and ai_full_midpoints:
        stats["blind_vs_full"] = compute_agreement(ai_blind_midpoints, ai_full_midpoints)

    return stats


# ═══════════════════════════════════════════════
#  AI 评分接口
# ═══════════════════════════════════════════════

def score_resume(coordinator, resume_text: str, category: str,
                 blind: bool = False) -> Optional[dict]:
    """通过 Coordinator 调用 AI 评分"""
    try:
        text = anonymize_resume(resume_text) if blind else resume_text
        result = coordinator.execute_tool(
            "evaluate_resume",
            resume_text=text,
            category=category,
            n_samples=3,
        )
        # 提取 overall 分数
        scores = result.get("scores", result)
        if isinstance(scores, dict):
            return {
                "overall": scores.get("overall"),
                "details": scores,
            }
        return None
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════
#  Session State Key 管理
# ═══════════════════════════════════════════════

_EXP_SESSION_KEYS = [
    "exp_current_resume",
    "exp_l1",
    "exp_l2",
    "exp_l3",
    "exp_final_range",
    "exp_scorer_name",
    "exp_status",
    "exp_ai_blind_done",
    "exp_ai_full_done",
    "exp_translated_text",
    "exp_dim_scores",
    "exp_ref_resume",
    "exp_ref_translated",
    "exp_selected_categories",
]


def _init_session_state():
    for k in _EXP_SESSION_KEYS:
        if k not in st.session_state:
            st.session_state[k] = None
    if "exp_scorer_name" not in st.session_state:
        st.session_state.exp_scorer_name = ""


# ═══════════════════════════════════════════════
#  UI 组件
# ═══════════════════════════════════════════════

def _translate_to_chinese(text: str) -> str:
    """调用 DeepSeek 将英文简历翻译为中文"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from openai import OpenAI
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=60,
        )
        resp = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[
                {"role": "system", "content": "你是一个翻译专家。把英文简历翻译成地道的中文，要求：\n1. 所有内容都要翻译成中文，包括标题、公司名、技能名、学校名\n2. 唯一保留英文的：纯技术名词首次出现时可括号标注英文（如 Python、Java）\n3. 修复原文中的拼写错误（如 Exprience→Experience）\n4. 语序调整为中文习惯，不要直译\n5. 只输出翻译结果，不加任何解释说明"},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[翻译失败: {e}]"


def _analyze_dimensions(resume_text: str, category: str) -> dict:
    """AI 分析各维度得分（仅维度分，不返回总分）"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from modules.resume_evaluator import ResumeEvaluator
        evaluator = ResumeEvaluator()
        result = evaluator.evaluate(resume_text, category, n_samples=1)
        dims = {}
        for d in result.get("dimensions", []):
            dims[d["key"]] = {
                "label": d["label"],
                "score": d["score"],
                "color": d.get("color", "#888"),
                "weight": d.get("weight", 0),
            }
        return dims
    except Exception as e:
        return {"error": str(e)}


def _get_ref_resume(category: str) -> dict:
    """从Kaggle同类别中取最长简历作为优秀参考"""
    df = _read_kaggle_csv()
    subset = df[df["Category"] == category]
    if len(subset) == 0:
        return None
    s = subset.copy()
    s["_len"] = s["Resume"].str.len()
    best = s.sort_values("_len", ascending=False).iloc[0]
    return {
        "category": category,
        "resume_text": best["Resume"],
        "length": int(best["_len"]),
    }


def render_human_scoring_ui():
    """人工评分界面 — 层级区间选择"""
    _init_session_state()
    experiments = _load_experiments()
    done_ids = {e["resume_id"] for e in experiments if e.get("human_score")}

    st.markdown("""
    <div class="page-header">
        <div class="page-title">双盲实验 · 人工评分</div>
        <div class="page-subtitle">随机抽取简历 → 脱敏显示 → 层级区间评分 → AI 对比</div>
    </div>
    """, unsafe_allow_html=True)

    # 评分人姓名
    col_name, _, _ = st.columns([2, 2, 6])
    with col_name:
        scorer = st.text_input("评分人", value=st.session_state.exp_scorer_name,
                               placeholder="输入你的名字", key="exp_scorer_input")
        st.session_state.exp_scorer_name = scorer

    # ── 选择你懂的类别 ──
    all_cats = sorted(_read_kaggle_csv()["Category"].unique().tolist())
    saved_cats = st.session_state.get("exp_selected_categories")
    selected_cats = st.multiselect(
        "选择你熟悉的岗位类别（仅从这些类别中抽取简历评分）",
        options=all_cats,
        default=saved_cats if saved_cats else [],
        key="exp_cat_selector",
    )
    st.session_state.exp_selected_categories = selected_cats

    # 统计可评数量
    df_all = _read_kaggle_csv()
    if selected_cats:
        df_filtered = df_all[df_all["Category"].isin(selected_cats)]
        total_avail = len(df_filtered)
        done_in_cats = {e["resume_id"] for e in experiments if e.get("human_score")
                        and e.get("category") in selected_cats}
        remaining = total_avail - len(done_in_cats)
    else:
        total_avail = len(df_all)
        done_in_cats = {e["resume_id"] for e in experiments if e.get("human_score")}
        remaining = total_avail - len(done_in_cats)

    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("你可评的简历", total_avail if selected_cats else "全部962份")
    col_stat2.metric("已评", len(done_in_cats))
    col_stat3.metric("待评", max(0, remaining))

    st.markdown("---")

    # ── 抽取简历 ──
    draw_btn = st.button("🎲 抽取简历", use_container_width=True, type="primary",
                         disabled=(remaining <= 0))

    if draw_btn:
        excluded = done_ids | {st.session_state.exp_current_resume.get("id")
                                for _ in [0] if st.session_state.exp_current_resume}
        resumes = _get_random_resumes(1, exclude_ids=excluded if excluded else None,
                                       categories=selected_cats if selected_cats else None)
        if resumes:
            r = resumes[0]
            st.session_state.exp_current_resume = r
            st.session_state.exp_l1 = None
            st.session_state.exp_l2 = None
            st.session_state.exp_l3 = None
            st.session_state.exp_final_range = None
            st.session_state.exp_status = "scoring"
            st.session_state.exp_ai_blind_done = False
            st.session_state.exp_ai_full_done = False
            st.session_state.exp_translated_text = None
            st.session_state.exp_dim_scores = None
            st.session_state.exp_ref_resume = None
            st.session_state.exp_ref_translated = None
            # 跑 AI 维度分析和找参考简历
            with st.spinner("AI 正在分析各维度..."):
                st.session_state.exp_dim_scores = _analyze_dimensions(r["resume_text"], r["category"])
            ref = _get_ref_resume(r["category"])
            st.session_state.exp_ref_resume = ref
            if ref:
                with st.spinner("正在翻译参考简历..."):
                    st.session_state.exp_ref_translated = _translate_to_chinese(
                        anonymize_resume(ref["resume_text"])
                    )
            st.rerun()
        else:
            st.info("所有简历已评完！")

    resume = st.session_state.exp_current_resume
    if not resume:
        st.info("点击「抽取简历」开始评分")
        return

    anonymized = anonymize_resume(resume["resume_text"])

    # ── AI 维度分析参考 ──
    dim_scores = st.session_state.exp_dim_scores
    if dim_scores and "error" not in dim_scores:
        st.markdown("#### 🤖 AI 维度分析（参考，不计入总分）")
        dim_cols = st.columns(len(dim_scores))
        _dim_order = ["skills_match", "project_quality", "education", "format_readability", "expression"]
        for i, key in enumerate(_dim_order):
            d = dim_scores.get(key)
            if d:
                bg = d["color"]
                with dim_cols[i]:
                    st.markdown(
                        f"<div style='text-align:center;background:{bg}15;"
                        f"border-radius:12px;padding:10px;margin:4px;'>"
                        f"<div style='font-size:13px;color:#666;'>{d['label']}</div>"
                        f"<div style='font-size:32px;font-weight:700;color:{bg};'>{int(d['score'])}</div>"
                        f"<div style='font-size:11px;color:#999;'>权重 {int(d['weight']*100)}%</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
        st.caption("💡 这是AI对每项的分析评分，作为你打总分的参考，不是标准答案")
        st.markdown("---")

    # ── 优秀参考简历 ──
    ref = st.session_state.exp_ref_resume
    ref_tl = st.session_state.exp_ref_translated
    if ref:
        ref_anon = anonymize_resume(ref["resume_text"])
        with st.expander(f"📋 同类优秀参考 · {ref['category']}（{ref['length']}字）", expanded=False):
            display_ref = ref_tl if ref_tl else ref_anon
            st.text_area("参考简历", display_ref, height=200, label_visibility="collapsed",
                         key="exp_ref_display")
            if ref_tl:
                st.caption("已翻译为中文 | 同类中最详细的简历，供对照参考")

    # ── 简历原文 ──
    tabs_en_cn = st.tabs(["🇬🇧 英文原文", "🇨🇳 中文翻译"])
    with tabs_en_cn[0]:
        st.text_area("英文", anonymized, height=280, label_visibility="collapsed",
                     key="exp_resume_en")
    with tabs_en_cn[1]:
        if st.session_state.exp_translated_text is None:
            if st.button("▶ 翻译为中文", key="exp_do_translate", type="primary",
                         use_container_width=True):
                with st.spinner("正在翻译..."):
                    st.session_state.exp_translated_text = _translate_to_chinese(anonymized)
                st.rerun()
            st.caption("点击按钮翻译为中文，技能/技术名词保留英文")
        else:
            st.text_area("中文", st.session_state.exp_translated_text, height=280,
                         label_visibility="collapsed", key="exp_resume_cn")
            if st.button("✕ 清除翻译", key="exp_clear_translate"):
                st.session_state.exp_translated_text = None
                st.rerun()

    st.markdown("---")

    # ── 层级评分 ──
    if st.session_state.exp_status == "scoring":
        st.markdown("#### 📊 总体评分")
        st.caption("依次选择层级，越细越好，不直接打分")

        # Level 1
        l1_options = list(SCORING_TREE.keys())
        l1_default = l1_options.index(st.session_state.exp_l1) if st.session_state.exp_l1 in l1_options else 0
        l1 = st.radio("层级一：整体印象", l1_options, index=l1_default, horizontal=True,
                       key="exp_l1_radio")
        st.session_state.exp_l1 = l1

        l1_node = SCORING_TREE[l1]
        l1_range = l1_node["range"]
        st.caption(f"当前范围: {l1_range[0]} — {l1_range[1]} 分")

        # Level 2
        if "children" in l1_node:
            l2_options = list(l1_node["children"].keys())
            l2_default = l2_options.index(st.session_state.exp_l2) if st.session_state.exp_l2 in l2_options else 0
            l2 = st.radio("层级二：细分", l2_options, index=l2_default, horizontal=True,
                           key="exp_l2_radio")
            st.session_state.exp_l2 = l2

            l2_node = l1_node["children"][l2]
            l2_range = l2_node["range"]
            st.caption(f"当前范围: {l2_range[0]} — {l2_range[1]} 分")

            # Level 3
            if "children" in l2_node:
                l3_options = list(l2_node["children"].keys())
                l3_default = l3_options.index(st.session_state.exp_l3) if st.session_state.exp_l3 in l3_options else 0
                l3 = st.radio("层级三：精确区间", l3_options, index=l3_default, horizontal=True,
                               key="exp_l3_radio")
                st.session_state.exp_l3 = l3

                l3_range = l2_node["children"][l3]
                st.caption(f"最终范围: {l3_range[0]} — {l3_range[1]} 分")
                final_range = l3_range
            else:
                final_range = l2_range
        else:
            final_range = l1_range

        st.session_state.exp_final_range = list(final_range)

        # ── 提交评分 ──
        st.markdown("---")
        if st.button("✅ 提交评分", type="primary", use_container_width=True):
            if not scorer:
                st.error("请先输入评分人姓名")
            else:
                # 保存人工评分
                lo, hi = final_range
                midpoint = (lo + hi) / 2

                # 查找或创建实验记录
                existing = None
                for exp in experiments:
                    if exp["resume_id"] == resume["id"]:
                        existing = exp
                        break

                if not existing:
                    existing = {
                        "id": f"exp_{int(time.time())}",
                        "resume_id": resume["id"],
                        "category": resume["category"],
                        "resume_text": resume["resume_text"],
                        "resume_anonymized": anonymized,
                        "human_score": None,
                        "ai_score_blind": None,
                        "ai_score_full": None,
                        "created_at": datetime.now().isoformat(),
                    }
                    experiments.append(existing)

                # 更新人工评分
                existing["human_score"] = {
                    "l1": l1.split(" (")[0],
                    "l2": l2.split(" (")[0] if l2 else None,
                    "l3": l3.split(" (")[0] if l3 else None,
                    "range_lo": lo,
                    "range_hi": hi,
                    "midpoint": midpoint,
                    "scorer": scorer,
                    "scored_at": datetime.now().isoformat(),
                }

                _save_experiments(experiments)
                st.session_state.exp_status = "done"
                st.success(f"评分已提交！区间: {lo}-{hi} 分, 中点: {midpoint} 分")
                st.rerun()

    # ── 评分完成状态 ──
    elif st.session_state.exp_status == "done":
        if st.session_state.exp_final_range:
            lo, hi = st.session_state.exp_final_range
            st.success(f"✅ 已评分 — 区间 {lo}-{hi} 分（中点: {(lo+hi)/2} 分）")

        if st.button("继续评分下一份", use_container_width=True):
            st.session_state.exp_status = "ready"
            st.session_state.exp_current_resume = None
            st.rerun()


def render_ai_experiment_ui():
    """AI 批量评分界面 — 对已有人工评分的简历跑 AI 评分"""
    _init_session_state()
    experiments = _load_experiments()

    st.markdown("""
    <div class="page-header">
        <div class="page-title">AI 批量评分</div>
        <div class="page-subtitle">对已有人工评分的简历运行 AI 评估（脱敏版 + 完整版）</div>
    </div>
    """, unsafe_allow_html=True)

    # 统计
    total = len(experiments)
    with_human = sum(1 for e in experiments if e.get("human_score"))
    with_blind = sum(1 for e in experiments if e.get("ai_score_blind"))
    with_full = sum(1 for e in experiments if e.get("ai_score_full"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("实验总数", total)
    c2.metric("已有人工评分", with_human)
    c3.metric("AI 脱敏评分", with_blind)
    c4.metric("AI 完整评分", with_full)

    st.markdown("---")

    # 需要跑 AI 评分的简历
    pending_blind = [e for e in experiments if e.get("human_score") and not e.get("ai_score_blind")]
    pending_full = [e for e in experiments if e.get("human_score") and not e.get("ai_score_full")]

    if not pending_blind and not pending_full:
        st.success("所有已有人工评分的简历已完成 AI 评分！")
        return

    if pending_blind:
        st.warning(f"还有 {len(pending_blind)} 份简历需要跑 AI 脱敏评分")
        if st.button("▶ 运行 AI 脱敏评分", type="primary"):
            _run_ai_batch(experiments, blind=True)
            st.rerun()

    if pending_full:
        st.info(f"还有 {len(pending_full)} 份简历需要跑 AI 完整评分")
        if st.button("▶ 运行 AI 完整评分"):
            _run_ai_batch(experiments, blind=False)
            st.rerun()


def _run_ai_batch(experiments: list, blind: bool):
    """批量运行 AI 评分，每个实验调用一次"""
    from modules.coordinator import AgentCoordinator
    coordinator = AgentCoordinator()

    key = "ai_score_blind" if blind else "ai_score_full"
    label = "脱敏版" if blind else "完整版"

    pending = [e for e in experiments if e.get("human_score") and not e.get(key)]
    if not pending:
        return

    progress = st.progress(0, text=f"正在运行 AI {label}评分...")
    status_text = st.empty()

    for i, exp in enumerate(pending):
        status_text.text(f"[{i+1}/{len(pending)}] {exp['category']} — {label}")
        result = score_resume(
            coordinator,
            resume_text=exp["resume_text"],
            category=exp["category"],
            blind=blind,
        )
        exp[key] = result
        _save_experiments(experiments)
        progress.progress((i + 1) / len(pending))

    status_text.text(f"✅ {label}评分完成，共 {len(pending)} 份")
    _save_experiments(experiments)


def render_experiment_dashboard():
    """实验结果看板 — 人机对比分析"""
    experiments = _load_experiments()

    st.markdown("""
    <div class="page-header">
        <div class="page-title">实验结果分析</div>
        <div class="page-subtitle">人机评分一致性 · 脱敏对比 · Bland-Altman</div>
    </div>
    """, unsafe_allow_html=True)

    if not experiments:
        st.info("暂无实验数据，请先在「人工评分」页面评分")
        return

    # ── 提取数据 ──
    rows = []
    for exp in experiments:
        hs = exp.get("human_score")
        ai_b = exp.get("ai_score_blind")
        ai_f = exp.get("ai_score_full")
        row = {
            "id": exp.get("id", ""),
            "category": exp.get("category", ""),
            "scorer": hs.get("scorer", "-") if hs else "-",
        }
        if hs:
            row["human_mid"] = hs.get("midpoint")
            row["human_range"] = f"{hs.get('range_lo')}-{hs.get('range_hi')}"
        if ai_b and ai_b.get("overall"):
            row["ai_blind"] = ai_b["overall"]
        if ai_f and ai_f.get("overall"):
            row["ai_full"] = ai_f["overall"]
        rows.append(row)

    df = pd.DataFrame(rows)
    has_human = "human_mid" in df.columns and df["human_mid"].notna().any()
    has_blind = "ai_blind" in df.columns and df["ai_blind"].notna().any()
    has_full = "ai_full" in df.columns and df["ai_full"].notna().any()

    # ── 数据表 ──
    with st.expander("📋 实验数据明细", expanded=True):
        display_cols = ["id", "category", "scorer"]
        if has_human:
            display_cols += ["human_mid", "human_range"]
        if has_blind:
            display_cols.append("ai_blind")
        if has_full:
            display_cols.append("ai_full")
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── 统计指标 ──
    stats = get_experiment_stats(experiments)
    if stats.get("total", 0) > 0:
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("实验总量", stats["total"])
        sc2.metric("人评数量", stats.get("human_count", 0))
        sc3.metric("AI 评分数量", stats.get("ai_blind_count", 0))

    # ── 散点图 ──
    st.markdown("#### 人机评分散点图")

    plot_data = []
    for _, row in df.iterrows():
        if pd.notna(row.get("human_mid")) and pd.notna(row.get("ai_blind")):
            plot_data.append({
                "人类评分": row["human_mid"],
                "AI评分(脱敏)": row["ai_blind"],
                "类别": row["category"],
                "对比": "人 vs AI(脱敏)",
            })
        if pd.notna(row.get("human_mid")) and pd.notna(row.get("ai_full")):
            plot_data.append({
                "人类评分": row["human_mid"],
                "AI评分(完整)": row["ai_full"],
                "类别": row["category"],
                "对比": "人 vs AI(完整)",
            })
        if pd.notna(row.get("ai_blind")) and pd.notna(row.get("ai_full")):
            plot_data.append({
                "人类评分": row["ai_blind"],
                "AI评分(完整)": row["ai_full"],
                "类别": row["category"],
                "对比": "AI(脱敏) vs AI(完整)",
            })

    if plot_data:
        pdf = pd.DataFrame(plot_data)
        # 动态选择可用的评分列
        avail_y = [c for c in ["AI评分(脱敏)", "AI评分(完整)"] if c in pdf.columns]
        if not avail_y:
            st.info("暂无足够的评分数据绘制散点图")
        else:
            y_col = avail_y[0]
            fig = px.scatter(pdf, x="人类评分", y=y_col,
                             color="类别", symbol="对比",
                             opacity=0.7,
                             labels={"人类评分": "人类评分 (中点)", y_col: "AI 评分"},
                             width=None, height=500)
            fig.add_annotation(
                x=85, y=85,
                text="y=x (完美一致)",
                showarrow=False,
                font=dict(color="gray", size=12),
            )
            fig.add_shape(type="line", x0=0, y0=0, x1=100, y1=100,
                           line=dict(color="gray", width=1, dash="dash"))
            fig.update_layout(
                plot_bgcolor="var(--surface)",
                paper_bgcolor="var(--surface)",
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("数据不足，请先运行 AI 评分")

    # ── Bland-Altman 图 ──
    st.markdown("#### Bland-Altman 一致性分析")
    if has_human and (has_blind or has_full):
        ba_data = []
        for _, row in df.iterrows():
            if pd.notna(row.get("human_mid")) and pd.notna(row.get("ai_blind")):
                avg = (row["human_mid"] + row["ai_blind"]) / 2
                diff = row["human_mid"] - row["ai_blind"]
                ba_data.append({"均值": avg, "差值": diff, "对比": "人 vs AI(脱敏)", "类别": row["category"]})
            if pd.notna(row.get("human_mid")) and pd.notna(row.get("ai_full")):
                avg = (row["human_mid"] + row["ai_full"]) / 2
                diff = row["human_mid"] - row["ai_full"]
                ba_data.append({"均值": avg, "差值": diff, "对比": "人 vs AI(完整)", "类别": row["category"]})

        if ba_data:
            bdf = pd.DataFrame(ba_data)
            mean_diff = bdf["差值"].mean()
            std_diff = bdf["差值"].std()
            fig_ba = px.scatter(bdf, x="均值", y="差值", color="类别",
                                symbol="对比", opacity=0.7, height=400)
            fig_ba.add_hline(y=mean_diff, line_color="green", line_width=2,
                              annotation_text=f"均值差 {mean_diff:.1f}")
            fig_ba.add_hline(y=mean_diff + 1.96 * std_diff, line_color="red", line_width=1, line_dash="dash",
                              annotation_text=f"+1.96SD {mean_diff + 1.96*std_diff:.1f}")
            fig_ba.add_hline(y=mean_diff - 1.96 * std_diff, line_color="red", line_width=1, line_dash="dash",
                              annotation_text=f"-1.96SD {mean_diff - 1.96*std_diff:.1f}")
            fig_ba.update_layout(
                plot_bgcolor="var(--surface)",
                paper_bgcolor="var(--surface)",
                margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig_ba, use_container_width=True)
    else:
        st.info("数据不足，请先完成人工评分和 AI 评分")

    # ── 一致性指标卡片 ──
    for key, label in [("human_vs_blind", "人 vs AI(脱敏)"),
                        ("human_vs_full", "人 vs AI(完整)"),
                        ("blind_vs_full", "AI(脱敏) vs AI(完整)")]:
        s = stats.get(key)
        if s and not s.get("error"):
            with st.container():
                sc = st.columns(5)
                sc[0].metric(f"{label} Pearson r", s.get("pearson_r", "-"))
                sc[1].metric(f"{label} MAE", f'{s.get("mae", "-")} 分')
                sc[2].metric(f"{label} 均值差", f'{s.get("mean_diff", "-")} 分')
                sc[3].metric(f"{label} 人类均值", s.get("human_mean", "-"))
                sc[4].metric(f"{label} AI均值", s.get("ai_mean", "-"))


def render_experiment_page():
    """双盲实验总入口"""
    tabs = st.tabs(["🎯 人工评分", "🤖 AI 评分", "📊 结果分析"])

    with tabs[0]:
        render_human_scoring_ui()

    with tabs[1]:
        render_ai_experiment_ui()

    with tabs[2]:
        render_experiment_dashboard()
