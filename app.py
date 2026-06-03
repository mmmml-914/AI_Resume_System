"""
AI 模拟面试系统
核心功能：简历输入 → AI 模拟面试 → 面试评估报告
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os, sys, json

sys.path.insert(0, os.path.dirname(__file__))
from modules.agent_workflow import WorkflowAgent
from modules.knowledge_base import ResumeKnowledgeBase
from modules.resume_collector import ResumeCollector
from modules.record_manager import RecordsManager
from modules.data_analysis import load_analysis
from modules.scoring_validation import load_validation
from modules.scoring_calibration import load_calibration
from utils.file_utils import extract_text_from_upload

st.set_page_config(page_title="AI Mock Interview", page_icon="🎤", layout="wide")

# ========== 统一数据持久化 ==========
_DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "app_data.json")

def _save_all():
    """保存所有状态 + 评估记录到一个文件"""
    session_keys = ["resume_text", "report", "interview_messages", "interview_status",
                    "interview_report", "agent_chat_messages", "polish_result"]
    data = {"version": "2.0", "session": {}, "records": []}

    for k in session_keys:
        v = st.session_state.get(k)
        if v is not None and v != [] and v != {}:
            data["session"][k] = v

    # 保存评估记录
    if "records_mgr" in st.session_state:
        data["records"] = st.session_state.records_mgr.get_all()

    os.makedirs(os.path.dirname(_DATA_FILE), exist_ok=True)
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)

def _load_all():
    """从单个文件恢复所有数据"""
    if not os.path.exists(_DATA_FILE):
        return {}
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, OSError):
        return {}

# ========== 加载 CSS ==========
with open(os.path.join(os.path.dirname(__file__), "styles", "style.css"), encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ========== 顶部导航栏 ==========
st.markdown('<div class="app-header"><div class="logo">AI Resume <span>System</span></div><div class="badge">v2.0</div></div>', unsafe_allow_html=True)

st.markdown('<div class="main-content">', unsafe_allow_html=True)

# ========== 初始化 ==========
if "agent" not in st.session_state:
    st.session_state.agent = WorkflowAgent()
if "knowledge_base" not in st.session_state:
    st.session_state.knowledge_base = ResumeKnowledgeBase()
if "records_mgr" not in st.session_state:
    st.session_state.records_mgr = RecordsManager()
if "report" not in st.session_state:
    st.session_state.report = None
if "resume_text" not in st.session_state:
    st.session_state.resume_text = None
if "collector" not in st.session_state:
    st.session_state.collector = ResumeCollector()
if "interview_messages" not in st.session_state:
    st.session_state.interview_messages = []
if "interview_status" not in st.session_state:
    st.session_state.interview_status = "idle"
if "interview_report" not in st.session_state:
    st.session_state.interview_report = None
if "interview_session" not in st.session_state:
    st.session_state.interview_session = None
if "interview_category" not in st.session_state:
    st.session_state.interview_category = ""
if "agent_chat_messages" not in st.session_state:
    st.session_state.agent_chat_messages = []
if "polish_result" not in st.session_state:
    st.session_state.polish_result = None
if "session_restored" not in st.session_state:
    saved = _load_all()
    if saved:
        # 恢复 session 状态
        for k, v in saved.get("session", {}).items():
            st.session_state[k] = v
        # 恢复评估记录
        records = saved.get("records", [])
        if records and "records_mgr" in st.session_state:
            st.session_state.records_mgr.load_all(records)
        st.session_state.session_restored = True
    else:
        st.session_state.session_restored = False

kb = st.session_state.knowledge_base
agent = st.session_state.agent
collector = st.session_state.collector


# ========== 侧边栏 ==========
with st.sidebar:
    st.markdown('<div class="sidebar-brand"><div class="brand-name">AI Interview</div><div class="brand-desc">模拟面试系统</div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # 导航
    page = st.radio("", [
        "模拟面试",
        "AI 助手",
        "简历润色",
        "简历采集",
        "批量测试",
        "数据看板",
    ], label_visibility="collapsed")

    st.markdown("---")

    # 数据集信息
    with st.expander("数据集"):
        st.markdown(f"**Kaggle**: {len(kb.kaggle_df) if kb.kaggle_df is not None else 0} 份简历")
        st.markdown(f"**岗位类别**: {len(kb.categories)} 个")
        stats = collector.get_stats()
        st.markdown(f"**优秀简历库**: {stats['total']} 份")
        if stats['categories']:
            for cat, cnt in stats['categories'].items():
                st.markdown(f"&nbsp;&nbsp;{cat}: {cnt} 份")

    st.markdown("---")
    st.markdown('<div class="sidebar-footer">v2.0 · 大数据课程项目</div>', unsafe_allow_html=True)

    if st.session_state.get("session_restored"):
        st.markdown('<div style="font-size:0.75rem;color:#4F46E5;text-align:center">💾 已恢复上次进度</div>', unsafe_allow_html=True)


# ========== 模拟面试页面 ==========
if page == "模拟面试":
    st.markdown('<div class="page-header"><div class="page-title">模拟面试</div><div class="page-subtitle">简历评估 + AI 模拟面试</div></div>', unsafe_allow_html=True)
    report = st.session_state.get("report")
    resume_text = st.session_state.get("resume_text")
    interview_status = st.session_state.interview_status

    # 状态: idle → active → ended
    if interview_status == "idle":
        if not resume_text or not report:
            # 首次使用，直接在此输入简历
            st.markdown("### 输入简历开始面试")

            col_left, col_right = st.columns([1, 1])
            with col_left:
                input_method = st.radio("输入方式", ["粘贴文本", "上传文件"], horizontal=True)
                new_resume = None
                if input_method == "粘贴文本":
                    new_resume = st.text_area("粘贴简历内容", height=280,
                                               placeholder="将简历文本粘贴至此...\n\n包括：技能、教育背景、实习经历、项目经验等")
                else:
                    uploaded = st.file_uploader("上传简历文件", type=["txt", "pdf", "docx", "doc", "png", "jpg", "jpeg"],
                                                 label_visibility="collapsed")
                    if uploaded is not None:
                        if uploaded.type and uploaded.type.startswith("image"):
                            st.info("首次处理图片需下载 OCR 模型 (~100MB)，可能需要 30-60 秒，请耐心等待")
                        new_resume = extract_text_from_upload(uploaded)
                        if new_resume:
                            st.success(f"已识别: {uploaded.name} ({len(new_resume)} 字符)")
            with col_right:
                new_category = st.selectbox("目标岗位", [""] + kb.categories)
                st.markdown("&nbsp;")
                st.markdown("&nbsp;")
                if st.button("🎤 开始模拟面试", type="primary", use_container_width=True):
                    resume_for_eval = new_resume or st.session_state.get("new_resume_input", "")
                    if resume_for_eval and len(resume_for_eval) > 50 and new_category:
                        with st.spinner("全流程分析简历中..."):
                            new_report = agent.pipeline_full_evaluation(resume_for_eval, new_category)
                            st.session_state.resume_text = resume_for_eval
                            st.session_state.report = new_report
                            st.session_state.interview_category = new_category
                            _save_all()
                            st.rerun()
                    else:
                        st.warning("请填写岗位类别和至少50字的简历内容")
        else:
            # 已有评估结果，直接开始面试
            st.markdown("### 简历评估摘要")
            cols = st.columns(5)
            dims = report.get("dimensions", [])
            for i, d in enumerate(dims):
                cols[i].metric(d["label"], f"{d['score']}/100")

            if report.get("weaknesses"):
                with st.expander("⚠️ 评估指出的不足（面试将重点考察这些方面）"):
                    for w in report["weaknesses"]:
                        st.markdown(f"- {w}")

            if st.button("🎤 开始模拟面试", type="primary", use_container_width=True):
                with st.spinner("面试官正在准备..."):
                    from modules.interview_agent import InterviewSession
                    session = InterviewSession(resume_text, report)
                    first_q = session.start()
                    st.session_state.interview_session = session
                    st.session_state.interview_messages = [
                        {"role": "assistant", "content": first_q}
                    ]
                    st.session_state.interview_status = "active"
                    # 从 report 中提取岗位类别（如果没有保存过）
                    if "interview_category" not in st.session_state:
                        st.session_state.interview_category = "未知"
                    _save_all()
                    st.rerun()

            if st.button("🔄 清除数据重新开始"):
                for k in ["resume_text", "report", "interview_messages", "interview_session", "interview_category"]:
                    st.session_state[k] = None if k != "interview_messages" else []
                _save_all()
                st.rerun()

    elif interview_status == "active":
        session = st.session_state.interview_session
        messages = st.session_state.interview_messages

        # 对话记录
        for msg in messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 结束面试按钮（对话流底部）
        col_end1, col_end2, col_end3 = st.columns([1, 2, 1])
        with col_end2:
            answered = sum(1 for m in messages if m['role'] == 'user')
            st.markdown(f'<div style="text-align:center;color:#8896AB;font-size:0.85rem;margin:6px 0">已答 {answered} 题</div>',
                        unsafe_allow_html=True)
            if st.button("🔚 结束面试", type="primary", use_container_width=True):
                if not session:
                    st.session_state.interview_status = "idle"
                    st.rerun()
                with st.spinner("正在生成面试报告..."):
                    ireport = session.end_interview()
                    st.session_state.interview_report = ireport
                    st.session_state.interview_status = "ended"

                    # 自动保存面试记录到 RecordsManager
                    mgr = st.session_state.records_mgr
                    mgr.add_record({
                        "type": "interview",
                        "category": st.session_state.get("interview_category", "未知"),
                        "scores": {"overall": ireport.get("overall", 0)},
                        "strengths": ireport.get("strengths", []),
                        "weaknesses": ireport.get("weaknesses", []),
                        "summary": ireport.get("evaluation_gaps", "")[:200],
                        "interview_report": {
                            "dimensions": ireport.get("dimensions", {}),
                            "stats": ireport.get("stats", {}),
                            "suggestions": ireport.get("suggestions", []),
                        },
                    })

                    _save_all()
                    st.rerun()

        # 流式输入
        prompt = st.chat_input("输入你的回答...")
        if prompt:
            # 显示用户消息
            st.session_state.interview_messages.append(
                {"role": "user", "content": prompt}
            )
            with st.chat_message("user"):
                st.markdown(prompt)

            # 流式输出面试官回复
            with st.chat_message("assistant"):
                stream = session.chat_stream(prompt)
                full_response = st.write_stream(stream)

            st.session_state.interview_messages.append(
                {"role": "assistant", "content": full_response}
            )
            _save_all()
            st.rerun()

    elif interview_status == "ended":
        ireport = st.session_state.interview_report
        if not ireport or "error" in ireport:
            st.error(f"报告生成失败: {ireport.get('error', '未知')}" if ireport else "无报告数据")
        else:
            st.markdown("### 面试评估报告")

            # 总分
            col1, col2, col3 = st.columns(3)
            col1.metric("综合评分", f"{ireport.get('overall', 0)}/100")
            col2.metric("面试题数", ireport.get("stats", {}).get("total_questions", 0))
            col3.metric("简历评分", f"{report.get('overall', 0)}/100")

            # 维度评分
            dims_data = ireport.get("dimensions", {})
            if dims_data:
                st.markdown("#### 各维度评分")
                dim_names = {
                    "technical_accuracy": "技术准确性",
                    "communication": "沟通表达",
                    "problem_solving": "问题解决能力",
                    "domain_knowledge": "领域知识",
                }
                for key, label in dim_names.items():
                    if key in dims_data:
                        d = dims_data[key]
                        cols = st.columns([2, 4, 4])
                        cols[0].markdown(f"**{label}**")
                        cols[1].progress(d["score"] / 100)
                        cols[2].markdown(f"{d['score']} — {d.get('comment', '')}")

            # 对比雷达图
            eval_dims = {d["key"]: d["score"] for d in report.get("dimensions", [])}
            interview_dims = dims_data
            if eval_dims and interview_dims:
                st.markdown("#### 简历评估 vs 面试表现")
                # 映射面试维度到简历维度的大类
                label_map = {
                    "technical_accuracy": "技能匹配度",
                    "communication": "内容表达",
                    "problem_solving": "项目经验质量",
                    "domain_knowledge": "教育背景",
                }
                radar_categories = []
                eval_values = []
                interview_values = []
                for key, label in label_map.items():
                    if key in interview_dims:
                        radar_categories.append(label)
                        # 找到对应简历维度
                        eval_score = 0
                        for ed in report.get("dimensions", []):
                            if ed["label"] == label:
                                eval_score = ed["score"]
                                break
                        eval_values.append(eval_score)
                        interview_values.append(interview_dims[key]["score"])

                if radar_categories:
                    fig = go.Figure()
                    fig.add_trace(go.Scatterpolar(
                        r=eval_values, theta=radar_categories,
                        fill="toself", name="简历评估",
                        line_color="#4F46E5", fillcolor="rgba(79,70,229,0.2)",
                    ))
                    fig.add_trace(go.Scatterpolar(
                        r=interview_values, theta=radar_categories,
                        fill="toself", name="面试表现",
                        line_color="#06D6A0", fillcolor="rgba(6,214,160,0.2)",
                    ))
                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                        height=350, margin=dict(l=60, r=60, t=10, b=10),
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # 优缺点
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 💪 优势")
                for s in ireport.get("strengths", []):
                    st.markdown(f"✅ {s}")
            with c2:
                st.markdown("#### 📈 待提升")
                for w in ireport.get("weaknesses", []):
                    st.markdown(f"⚠️ {w}")

            # 改进建议
            st.markdown("#### 改进建议")
            for i, sug in enumerate(ireport.get("suggestions", []), 1):
                st.markdown(f"{i}. {sug}")

            # 差异分析
            gaps = ireport.get("evaluation_gaps")
            if gaps:
                with st.expander("简历评估 vs 面试表现差异分析"):
                    st.info(gaps)

            if st.button("重新面试", type="primary"):
                st.session_state.interview_session = None
                st.session_state.interview_messages = []
                st.session_state.interview_status = "idle"
                st.session_state.interview_report = None
                _save_all()
                st.rerun()


# ========== AI 助手页面 ==========
elif page == "AI 助手":
    st.markdown('<div class="page-header"><div class="page-title">AI 助手</div><div class="page-subtitle">自然语言交互 · 自动调用工具完成操作</div></div>', unsafe_allow_html=True)

    chat_history = st.session_state.agent_chat_messages

    # 显示对话历史
    for msg in chat_history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                content = msg["content"]
                if isinstance(content, dict):
                    if content.get("type") == "tool_calls":
                        for call in content.get("calls", []):
                            tool_name = call.get("tool", "")
                            tool_label = {
                                "parse_resume": "🔍 解析简历",
                                "evaluate_resume": "📊 评估简历",
                                "knowledge_lookup": "📚 查询知识库",
                                "polish_resume": "✨ 润色简历",
                                "collect_resume": "💾 保存简历",
                                "start_interview": "🎤 启动面试",
                                "interview_chat": "💬 面试对话",
                                "end_interview": "📋 结束面试",
                            }.get(tool_name, f"🛠 {tool_name}")

                            st.markdown(f"**{tool_label}**")
                            result = call.get("result", {})

                            if tool_name == "evaluate_resume":
                                cols = st.columns(5)
                                for d in result.get("dimensions", []):
                                    cols[list(result.get("dimensions", [])).index(d) if result.get("dimensions") else 0].metric(d["label"], f"{d['score']}/100")
                                st.metric("综合评分", f"{result.get('overall', 0)}/100")
                                with st.expander("详情"):
                                    st.json(result)

                            elif tool_name == "polish_resume":
                                if result.get("polished"):
                                    st.markdown(f'<div style="background:#F8FFFB;border:1px solid #D1FAE5;border-radius:12px;padding:14px 18px;font-size:0.92rem;line-height:1.7;white-space:pre-wrap">{result["polished"]}</div>', unsafe_allow_html=True)
                                if result.get("changes"):
                                    with st.expander(f"📝 {len(result['changes'])} 处修改"):
                                        for ch in result["changes"]:
                                            st.markdown(f'- **{ch.get("reason", "")}**')
                                            st.markdown(f'  - 原文: {ch.get("original", "")}')
                                            st.markdown(f'  - 优化: {ch.get("improved", "")}')
                                if result.get("keywords_added"):
                                    st.markdown("🏷 新增: " + ", ".join(f"`{k}`" for k in result["keywords_added"]))

                            elif tool_name == "knowledge_lookup":
                                samples = result.get("samples", [])
                                if samples:
                                    st.markdown(f"找到 {len(samples)} 份同类简历样本")
                                avg = result.get("avg_scores", {})
                                if avg:
                                    st.markdown(f"优秀简历平均分: {avg}")

                            elif tool_name == "start_interview":
                                st.info(f"面试已启动")
                                if result.get("question"):
                                    st.markdown(f'**面试官**: {result["question"][:200]}...')

                            elif tool_name == "collect_resume":
                                if result.get("success"):
                                    st.success("✅ 已保存到优秀简历库")

                            else:
                                st.json(result)
                    elif content.get("type") == "text":
                        st.markdown(content.get("content", ""))
                    else:
                        st.json(content)
                else:
                    st.markdown(str(content))

    # 输入
    prompt = st.chat_input("输入你的需求，如：帮我看下这份简历、润色并对比分数、查询知识库...")
    if prompt:
        chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("AI 思考中..."):
                context = {
                    "resume_text": st.session_state.get("resume_text", ""),
                    "report": st.session_state.get("report", {}),
                }
                response = agent.process_user_request(prompt, context)
            chat_history.append({"role": "assistant", "content": response})
            _save_all()
            st.rerun()


# ========== 简历润色页面 ==========
elif page == "简历润色":
    st.markdown('<div class="page-header"><div class="page-title">简历润色</div><div class="page-subtitle">用 AI 优化简历表达，突出量化成果，匹配目标岗位</div></div>', unsafe_allow_html=True)
    st.markdown("用 AI 优化简历表达，突出量化成果，匹配目标岗位")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("### 原始简历")
        polish_input_method = st.radio("输入方式", ["粘贴文本", "上传文件"], horizontal=True, key="polish_input")
        polish_input = None
        if polish_input_method == "粘贴文本":
            polish_input = st.text_area("粘贴需要润色的简历", height=350,
                                         placeholder="将简历文本粘贴至此...",
                                         value="")
        else:
            uploaded = st.file_uploader("上传简历文件", type=["txt", "pdf", "docx", "doc", "png", "jpg", "jpeg"],
                                         label_visibility="collapsed", key="polish_upload")
            if uploaded is not None:
                if uploaded.type and uploaded.type.startswith("image"):
                    st.info("首次处理图片需下载 OCR 模型 (~100MB)，可能需要 30-60 秒，请耐心等待")
                polish_input = extract_text_from_upload(uploaded)
                if polish_input:
                    st.success(f"已识别: {uploaded.name} ({len(polish_input)} 字符)")

        polish_category = st.selectbox("目标岗位", [""] + kb.categories, key="polish_cat")

        with st.expander("高级选项（可选）"):
            polish_focus = st.text_input("重点关注方向",
                                          placeholder="如：突出项目量化成果、强化技术栈描述等")

        if st.button("✨ 开始润色", type="primary", use_container_width=True):
            if polish_input and len(polish_input) > 50:
                from modules.resume_polisher import ResumePolisher
                polisher = ResumePolisher(llm_client=agent.llm)

                # 流式显示进度
                status_box = st.status("AI 正在优化简历...", expanded=True)
                progress = status_box.empty()
                full = ""
                for chunk in polisher.polish_stream(polish_input, polish_category, polish_focus):
                    full += chunk
                    progress.markdown(f"⏳ 已接收 {len(full)} 字符...")

                status_box.update(label="✅ 润色完成，解析结果中...", state="running")
                result = ResumePolisher._parse_result(full)
                status_box.update(label="✅ 润色完成", state="complete", expanded=False)

                st.session_state.polish_result = result
                _save_all()
                st.rerun()
            else:
                st.warning("请输入至少 50 字的简历内容")

    with col_right:
        result = st.session_state.get("polish_result")
        if result and "error" not in result:
            st.markdown("### 润色结果")
            st.markdown(
                f'<div style="background:#F8FFFB;border:1px solid #D1FAE5;border-radius:12px;'
                f'padding:14px 18px;font-size:0.92rem;line-height:1.7;white-space:pre-wrap">'
                f'{result["polished"]}</div>',
                unsafe_allow_html=True,
            )

            if result.get("changes"):
                with st.expander("📝 具体修改 " + str(len(result["changes"])) + " 处"):
                    for i, ch in enumerate(result["changes"], 1):
                        st.markdown(f"**{i}. 优化原因**: {ch.get('reason', '')}")
                        st.markdown(f'- 原文: "{ch.get("original", "")}"')
                        st.markdown(f'- 优化: "{ch.get("improved", "")}"')
                        st.markdown("---")

            if result.get("keywords_added"):
                with st.expander("🏷️ 新增关键词"):
                    for kw in result["keywords_added"]:
                        st.markdown(f"- `{kw}`")

            if result.get("suggestions"):
                st.markdown("#### 💡 整体建议")
                for s in result["suggestions"]:
                    st.markdown(f"- {s}")

            # 快捷复制
            st.markdown("&nbsp;")
            st.code(result["polished"], language="text")

        elif result and "error" in result:
            st.error(f"润色出错: {result['error']}")


# ========== 简历采集页面 ==========
elif page == "简历采集":
    st.markdown('<div class="page-header"><div class="page-title">简历采集</div><div class="page-subtitle">从网页批量采集优秀简历</div></div>', unsafe_allow_html=True)

    tab_collect, tab_browse, tab_bookmarklet = st.tabs(["添加简历", "浏览库", "采集工具"])

    with tab_collect:
        st.markdown("### 导入简历内容")
        st.markdown("可以**粘贴文本**或**上传截图**（OCR自动提取文字）：")

        collect_input_method = st.radio("输入方式", ["粘贴文本", "上传图片"], horizontal=True, key="collect_input_method")

        # 图片上传 → OCR
        collected_image_text = st.session_state.get("_collected_ocr_text", "")
        if collect_input_method == "上传图片":
            uploaded_img = st.file_uploader(
                "上传简历截图", type=["png", "jpg", "jpeg", "bmp", "tiff", "webp"],
                label_visibility="collapsed",
                key="collect_img_upload",
                help="支持小红书/抖音/牛客网/知乎的简历截图"
            )
            if uploaded_img is not None:
                with st.spinner("OCR 识别中..."):
                    from utils.file_utils import extract_text_from_upload
                    ocr_text = extract_text_from_upload(uploaded_img)
                    if ocr_text and len(ocr_text) > 20:
                        st.session_state["_collected_ocr_text"] = ocr_text
                        st.success(f"✅ OCR 识别完成：{len(ocr_text)} 字符，请核对下方文本后保存")
                    else:
                        st.warning("OCR 未能提取到有效文字，请尝试更清晰的截图或改用粘贴文本")
            if collected_image_text:
                st.info("💡 如识别有误，可直接在下文文本框中修改")

        col1, col2 = st.columns(2)
        with col1:
            cat_options = [""] + kb.categories
            new_category = st.selectbox("岗位类别", cat_options, key="collect_cat")
        with col2:
            source_options = ["小红书", "抖音", "牛客网", "知乎", "其他"]
            new_source = st.selectbox("来源平台", source_options)

        new_title = st.text_input("标题（如：211硕-字节跳动数据分析-offer）",
                                   placeholder="例如：双非本-拼多多数据分析-offer")
        new_background = st.text_input("背景简介（如：211硕士，统计学专业，拿到字节/美团offer）",
                                        placeholder="简要描述候选人的教育背景和offer情况")

        new_text = st.text_area("简历文本（支持中英文）", height=350,
                                 value=collected_image_text,
                                 placeholder="粘贴简历文本，或上传截图后 OCR 文字会自动填入...\n\n包括：技能、教育背景、实习经历、项目经验等",
                                 key="collect_text_area")

        col_left, col_right = st.columns([1, 3])
        with col_left:
            if st.button("保存到优秀简历库", type="primary", use_container_width=True):
                if new_text and len(new_text) > 100 and new_category:
                    result = agent.execute_tool("collect_resume",
                        category=new_category,
                        title=new_title or f"来自{new_source}的{new_category}简历",
                        source=new_source,
                        resume_text=new_text,
                        background=new_background)
                    if result.get("error"):
                        st.error(result["error"])
                    else:
                        # 刷新知识库
                        st.session_state.knowledge_base = ResumeKnowledgeBase()
                        stats = collector.get_stats()
                        st.success(f"✅ 已保存！优秀简历库现有 {stats['total']} 份简历")
                        _save_all()
                        st.rerun()
                else:
                    st.warning("请填写岗位类别和至少100字的简历内容")
        with col_right:
            st.markdown("&nbsp;")

        st.markdown("---")
        st.markdown("**采集技巧** 💡")
        tips = [
            "在小红书搜索 `拿到offer 简历`、`数据分析 简历 STAR`、`双非 简历 上岸`",
            "在牛客网搜索 `数据分析 offer`、`面经`，录取者常分享详细简历",
            "在知乎搜索 `数据分析 秋招 简历`，很多录取者会分享背景和简历内容",
            "关注简历中的**量化成果**（百分比、数字、效率提升）— 这是高质量简历的标志",
            "建议优先采集**有具体数据**的简历，评估对比效果更好",
        ]
        for tip in tips:
            st.markdown(f"- {tip}")

    with tab_browse:
        stats = collector.get_stats()
        st.markdown(f"**优秀简历库**: 共 {stats['total']} 份")

        categories = stats.get("categories", {})
        if categories:
            sel_cat = st.selectbox("筛选岗位", ["全部"] + list(categories.keys()))
            resumes = collector.resumes
            if sel_cat != "全部":
                resumes = [r for r in resumes if r.get("category") == sel_cat]

            for r in resumes:
                with st.expander(f"**{r.get('title', '未命名')}** — {r.get('category')} ({r.get('source')})"):
                    st.markdown(f"**背景**: {r.get('background', '无')}")
                    st.text(r["resume_text"][:500] + ("..." if len(r["resume_text"]) > 500 else ""))
                    if st.button("删除", key=f"del_{r['id']}"):
                        collector.resumes = [x for x in collector.resumes if x["id"] != r["id"]]
                        collector._save()
                        _save_all()
                        st.rerun()

    with tab_bookmarklet:
        st.markdown("### 浏览器书签采集工具")
        st.markdown("把下面的按钮拖到浏览器书签栏，在网页上选中简历文本后点击即可快速提取：")

        bookmarklet_code = """javascript:(function(){
  var t = window.getSelection().toString();
  if(!t||t.length<50){alert('请先选中简历文本（至少50字）');return;}
  var d = document.createElement('textarea');
  d.value = t;
  document.body.appendChild(d);
  d.select();
  document.execCommand('copy');
  document.body.removeChild(d);
  alert('已复制 '+t.length+' 字简历内容！\\n\\n请回到AI Resume System，粘贴到"添加简历"页面。');
})();"""

        st.code(bookmarklet_code, language="javascript")

        st.markdown("**使用步骤：**")
        steps = [
            "打开任一网页（小红书/抖音/牛客网/知乎）",
            "用鼠标选中简历文本内容",
            "点击书签栏的这个书签 → 自动复制选中文本",
            "回到本页面 → Ctrl+V 粘贴到「添加简历」区域",
            "选择岗位类别 → 点击保存",
        ]
        for i, step in enumerate(steps, 1):
            st.markdown(f"{i}. {step}")

        st.info("💡 如果书签无效，也可以手动复制文本后直接粘贴到「添加简历」页面")


# ========== 批量测试页面 ==========
elif page == "批量测试":
    st.markdown("### 🔬 批量简历评估测试")
    st.markdown('<div class="page-header"><div class="page-title">批量测试</div><div class="page-subtitle">多份简历批量评分对比</div></div>', unsafe_allow_html=True)
    mgr = st.session_state.records_mgr

    col_config, col_status = st.columns([1, 1])

    with col_config:
        st.markdown("**测试配置**")
        batch_category = st.selectbox("筛选岗位类别", ["全部"] + kb.categories)
        batch_count = st.slider("测试样本数", 3, 30, 10, step=5,
                                help="每次从Kaggle数据集中随机抽取N份简历进行评估（样本越多耗时越长，约30秒/份）")
        batch_run = st.button("🚀 开始批量测试", type="primary", use_container_width=True)

    with col_status:
        stats = mgr.get_stats()
        st.markdown("**累计测试统计**")
        c1, c2, c3 = st.columns(3)
        c1.metric("已测试简历", stats["total"])
        c2.metric("覆盖岗位", len(stats["categories"]) if stats["total"] > 0 else 0)
        avg_overall = stats.get("avg_scores", {}).get("overall", "-")
        c3.metric("平均分", avg_overall if avg_overall != "-" else "-")

    if batch_run:
        df = kb.kaggle_df
        if df is None:
            st.error("Kaggle 数据集未加载")
        else:
            # 筛选
            if batch_category != "全部":
                subset = df[df["Category"] == batch_category]
            else:
                subset = df
            sampled = subset.sample(n=min(batch_count, len(subset)))
            st.info(f"从「{batch_category}」中随机抽取 {len(sampled)} 份简历进行评估")

            progress_bar = st.progress(0, text="准备中...")
            status_text = st.empty()
            results_container = st.container()

            results = []
            errors = 0
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading

            samples_list = list(sampled.iterrows())
            results = [None] * len(samples_list)
            completed = 0
            _lock = threading.Lock()

            def _evaluate_one(idx, row):
                report = agent.pipeline_full_evaluation(row["Resume"], row["Category"])
                if report.get("workflow_status") != "failed":
                    dims = {d["key"]: d["score"] for d in report.get("dimensions", [])}
                    return idx, {
                        "category": row["Category"],
                        "scores": {"overall": report.get("overall", 0), **dims},
                        "strengths": report.get("strengths", [])[:2],
                        "weaknesses": report.get("weaknesses", [])[:2],
                        "summary": report.get("summary", "")[:200],
                    }
                return idx, None

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(_evaluate_one, idx, row): idx for idx, (_, row) in enumerate(samples_list)}
                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        _, record = future.result()
                        with _lock:
                            results[idx] = record
                            completed += 1
                            if record is None:
                                errors += 1
                            progress_bar.progress(
                                completed / len(samples_list),
                                text=f"已完成 {completed}/{len(samples_list)}"
                            )
                            status_text.markdown(
                                f"**进度**: 成功 {completed - errors}/{completed}，"
                                f"失败 {errors}，进行中 {len(samples_list) - completed}"
                            )
                    except Exception:
                        with _lock:
                            errors += 1
                            completed += 1
                            progress_bar.progress(
                                completed / len(samples_list),
                                text=f"已完成 {completed}/{len(samples_list)}"
                            )

            # 主线程批量添加，避免并发写文件
            valid_results = [r for r in results if r is not None]
            for record in valid_results:
                mgr.add_record(record)

            progress_bar.empty()
            status_text.empty()

            st.success(f"✅ 批量测试完成！成功 {len(valid_results)} 份，失败 {errors} 份")

            if results:
                # 简略结果表格
                result_df = pd.DataFrame([
                    {
                        "岗位类别": r["category"],
                        "综合评分": r["scores"]["overall"],
                        "技能匹配": r["scores"].get("skills_match", ""),
                        "项目质量": r["scores"].get("project_quality", ""),
                        "格式": r["scores"].get("format_readability", ""),
                        "教育": r["scores"].get("education", ""),
                        "表达": r["scores"].get("expression", ""),
                    }
                    for r in results
                ])
                st.dataframe(result_df, use_container_width=True, hide_index=True)

                # 快速对比图
                fig = px.bar(result_df, x="岗位类别", y="综合评分",
                             title="批量测试 — 各简历综合评分",
                             color="综合评分", color_continuous_scale="RdYlGn",
                             text_auto=True)
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)

    # 历史记录
    st.markdown("---")
    st.markdown("**测试历史**")
    records = mgr.get_records(limit=50)
    if records:
        hist_df = pd.DataFrame([
            {
                "时间": r.get("created_at", ""),
                "岗位": r.get("category", ""),
                "综合评分": r.get("scores", {}).get("overall", ""),
            }
            for r in records
        ])
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无测试记录，点击上方「开始批量测试」")


# ========== 数据看板页面 ==========
elif page == "数据看板":
    dash_section = st.radio("", ["Kaggle 数据集", "优秀简历库", "面试记录分析", "📊 深度分析"],
                            horizontal=True, label_visibility="collapsed")
    st.markdown('<div class="page-header"><div class="page-title">数据看板</div><div class="page-subtitle">数据集分析 · 评分验证 · RAG 状态</div></div>', unsafe_allow_html=True)
    st.markdown("---")

    if dash_section == "📊 深度分析":
        st.markdown("### 数据集深度分析")
        st.caption("基于 Kaggle UpdatedResumeDataSet.csv（962 份简历，25 个岗位类别）的文本挖掘结果")

        analysis = load_analysis()
        if not analysis:
            st.info("请先运行数据分析脚本：python modules/data_analysis.py")
        else:
            # 技能分布
            st.markdown("#### 技能关键词分布 Top 15")
            skill_overall = analysis.get("skill_stats", {}).get("overall", {})
            if skill_overall:
                sk_df = pd.DataFrame(
                    [{"技能": k, "出现次数": v} for k, v in list(skill_overall.items())[:15]]
                )
                fig_sk = px.bar(sk_df, x="技能", y="出现次数",
                                color="出现次数", color_continuous_scale="Viridis",
                                text_auto=True)
                fig_sk.update_layout(height=380)
                st.plotly_chart(fig_sk, use_container_width=True)

            # 岗位×技能热力图
            st.markdown("#### 岗位 × 技能 热力图")
            skill_per_cat = analysis.get("skill_stats", {}).get("per_category", {})
            if skill_per_cat:
                all_skills_list = list(skill_overall.keys())[:12]
                heat_data = []
                for cat, skills in skill_per_cat.items():
                    for sk in all_skills_list:
                        heat_data.append({"岗位": cat, "技能": sk, "出现次数": skills.get(sk, 0)})
                if heat_data:
                    heat_df = pd.DataFrame(heat_data)
                    fig_heat = px.density_heatmap(heat_df, x="技能", y="岗位", z="出现次数",
                                                   color_continuous_scale="Blues",
                                                   height=max(400, len(skill_per_cat) * 12))
                    st.plotly_chart(fig_heat, use_container_width=True)

            # 词频
            st.markdown("#### 简历高频词汇 Top 30")
            word_freq = analysis.get("word_freq", [])
            if word_freq:
                wf_df = pd.DataFrame(word_freq[:30])
                fig_wf = px.bar(wf_df, x="count", y="word", orientation="h",
                                color="count", color_continuous_scale="Oranges",
                                text_auto=True, labels={"count": "出现次数", "word": "词汇"})
                fig_wf.update_layout(height=500)
                st.plotly_chart(fig_wf, use_container_width=True)

            # 教育程度
            st.markdown("#### 教育程度关键词检测")
            edu_stats = analysis.get("education_stats", {})
            if edu_stats:
                edu_df = pd.DataFrame([
                    {"学历": {"bachelor": "本科/学士", "master": "硕士", "phd": "博士", "mba": "MBA"}.get(k, k),
                     "简历数": v} for k, v in edu_stats.items()
                ])
                col_e1, col_e2 = st.columns([1, 2])
                with col_e1:
                    st.dataframe(edu_df, hide_index=True, use_container_width=True)
                    st.caption("注：一份简历可能提及多个学历关键词")
                with col_e2:
                    fig_edu = px.pie(edu_df, names="学历", values="简历数",
                                     color_discrete_sequence=px.colors.sequential.Blues_r)
                    fig_edu.update_layout(height=280)
                    st.plotly_chart(fig_edu, use_container_width=True)

            # 统计概览
            st.markdown("#### 文本统计概览")
            cat_stats = analysis.get("category_stats", {})
            text_stats = analysis.get("text_stats", {})
            comp = analysis.get("complexity", {})
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("总简历数", cat_stats.get("total", "-"))
            c2.metric("岗位类别", cat_stats.get("total_categories", "-"))
            c3.metric("平均字数", text_stats.get("overall_avg", "-"))
            c4.metric("平均单词数", comp.get("avg_word_count", "-"))

            # RAG 状态
            st.markdown("---")
            try:
                from modules.rag_knowledge import get_chroma_collection
                rag_collection = get_chroma_collection()
                rag_count = rag_collection.count()
                rag_status = "已启用" if rag_count > 0 else "未构建"
            except Exception:
                rag_count = 0
                rag_status = "未构建"

            col_r1, col_r2, col_r3 = st.columns(3)
            col_r1.metric("RAG 知识库状态", rag_status, delta="检索增强评分" if rag_count > 0 else None)
            col_r2.metric("向量化简历数", rag_count)
            col_r3.metric("嵌入模型", "BAAI/bge-small-zh-v1.5" if rag_count > 0 else "-")
            with st.expander("什么是 RAG？"):
                st.markdown("""
                **RAG (Retrieval-Augmented Generation)** — 检索增强生成技术。

                评分时，系统自动从知识库中检索与被评简历 **同类岗位** 的 **真实简历样本**，
                将样本作为「参考上下文」注入到 AI 评分 prompt 中，让 AI 在了解同类候选人水平后再评分，
                使评分更客观、更有参照性。
                """)

            # 评分验证
            st.markdown("---")
            st.markdown("### 评分验证：单次 vs Multi-shot 对比")
            st.caption("从不同岗位各取1份简历，分别用 n_samples=1 和 n_samples=3 评估，对比波动")

            validation = load_validation()
            if validation and validation.get("samples"):
                samples = validation["samples"]
                valid_rows = []
                for s in samples:
                    valid_rows.append({
                        "岗位": s["category"],
                        "单次评分": s["single_overall"],
                        "3次均值": s["multi_overall"],
                        "差值": abs(s["single_overall"] - s["multi_overall"]),
                        "95% CI": f"±{s['multi_ci']}",
                        "分数范围": f"{s['ci_low']}-{s['ci_high']}",
                    })
                st.dataframe(pd.DataFrame(valid_rows), hide_index=True, use_container_width=True)

                # 对比图
                fig_v = go.Figure()
                for s in samples:
                    fig_v.add_trace(go.Bar(
                        name=s["category"],
                        x=["单次评分", "3次均值"],
                        y=[s["single_overall"], s["multi_overall"]],
                        text=[f"{s['single_overall']}", f"{s['multi_overall']}"],
                        textposition="auto",
                    ))
                fig_v.update_layout(title="单次 vs 3次评分对比", barmode="group",
                                    height=350, yaxis_title="综合分")
                st.plotly_chart(fig_v, use_container_width=True)

                with st.expander("查看各维度详细对比"):
                    for s in samples:
                        st.markdown(f"**{s['category']}** — 单次={s['single_overall']}  vs  3次均值={s['multi_overall']} (CI=±{s['multi_ci']})")
                        dim_rows = []
                        for d in s.get("dimensions", []):
                            dim_rows.append({
                                "维度": d["label"], "单次": d["single_score"],
                                "3次均值": d["multi_mean"], "95% CI": f"±{d['multi_ci']}",
                                "范围": f"{d['ci_low']}-{d['ci_high']}",
                            })
                        if dim_rows:
                            st.dataframe(pd.DataFrame(dim_rows), hide_index=True, use_container_width=True)
            else:
                st.info("请先运行验证脚本：python modules/scoring_validation.py")

            # 评分校准
            st.markdown("---")
            st.markdown("### 评分校准：AI 评分 vs 规则基线对比")
            st.caption("从 20 个岗位各取 1 份简历，对比 AI（Multi-shot N=3）与规则基线的评分差异")

            calibration = load_calibration()
            if calibration and calibration.get("samples"):
                cal_samples = calibration["samples"]
                cal_rows = []
                for s in cal_samples:
                    cal_rows.append({
                        "岗位": s["category"],
                        "AI评分": s["ai_overall"],
                        "基线评分": s["rule_overall"],
                        "差值": s["overall_diff"],
                    })
                cal_df = pd.DataFrame(cal_rows)
                cal_df = cal_df.sort_values("差值", ascending=False)

                col_c1, col_c2, col_c3 = st.columns(3)
                col_c1.metric("样本量", f"{calibration['n_samples']} 份")
                col_c2.metric("平均差值", f"{calibration['mean_diff']}")
                col_c3.metric("最大差值", f"{calibration['max_diff']}")

                st.dataframe(cal_df, hide_index=True, use_container_width=True)

                # 散点图: AI vs 规则
                fig_cal = px.scatter(cal_df, x="基线评分", y="AI评分", text="岗位",
                                     title="AI 评分 vs 规则基线评分（散点图）",
                     color="差值", color_continuous_scale="RdYlGn_r",
                     labels={"基线评分": "规则基线评分", "AI评分": "AI Multi-shot 评分"})
                fig_cal.update_traces(textposition="top center", marker_size=12)
                # 添加 y=x 参考线
                max_val = max(cal_df["AI评分"].max(), cal_df["基线评分"].max()) + 10
                fig_cal.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val],
                    mode="lines", name="y=x (完全一致)",
                    line=dict(dash="dash", color="gray", width=1)))
                fig_cal.update_layout(height=450)
                st.plotly_chart(fig_cal, use_container_width=True)

                # 差值分布柱状图
                fig_cal2 = px.bar(cal_df, x="岗位", y="差值",
                                  title="各岗位 AI vs 基线评分差值",
                                  color="差值", color_continuous_scale="RdYlGn_r",
                                  text_auto=True)
                fig_cal2.update_layout(height=350, xaxis_tickangle=-45)
                st.plotly_chart(fig_cal2, use_container_width=True)

                with st.expander("查看维度级详细对比"):
                    for s in cal_samples[:10]:
                        st.markdown(f"**{s['category']}** — AI={s['ai_overall']} vs 基线={s['rule_overall']} (diff={s['overall_diff']})")
                        da = s.get("ai_dimensions", {})
                        dr = s.get("rule_dimensions", {})
                        dim_comp = []
                        for k in ["skills_match", "project_quality", "format_readability", "education", "expression"]:
                            labels = {"skills_match":"技能匹配","project_quality":"项目经验","format_readability":"格式","education":"教育","expression":"表达"}
                            dim_comp.append({
                                "维度": labels.get(k, k),
                                "AI评分": da.get(k, {}).get("score", "-"),
                                "95% CI": f"±{da.get(k, {}).get('ci', '-')}",
                                "基线评分": dr.get(k, "-"),
                            })
                        st.dataframe(pd.DataFrame(dim_comp), hide_index=True, use_container_width=True)
            else:
                st.info("请先运行校准脚本：python modules/scoring_calibration.py")

    elif dash_section == "Kaggle 数据集":
        st.markdown(f"**UpdatedResumeDataSet.csv** — 962 份简历，25 个岗位类别")

        df = kb.kaggle_df
        if df is not None:
            cat_counts = df['Category'].value_counts().reset_index()
            cat_counts.columns = ['Category', 'Count']
            fig1 = px.bar(cat_counts, x='Category', y='Count',
                          title='岗位类别分布',
                          color='Count', color_continuous_scale='Blues',
                          text_auto=True)
            fig1.update_layout(height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig1, use_container_width=True)

            df['text_len'] = df['Resume'].str.len()
            fig2 = px.histogram(df, x='text_len', nbins=40,
                                title='简历文本长度分布',
                                color_discrete_sequence=['#4F46E5'],
                                labels={'text_len': '字符数', 'count': '数量'})
            fig2.update_layout(height=300)
            st.plotly_chart(fig2, use_container_width=True)

            avg_len = df.groupby('Category')['text_len'].mean().round(0).astype(int).reset_index()
            avg_len.columns = ['Category', 'Avg_Length']
            avg_len = avg_len.sort_values('Avg_Length', ascending=False)
            fig3 = px.bar(avg_len.head(10), x='Avg_Length', y='Category',
                          orientation='h', title='Top 10 — 平均简历长度',
                          color='Avg_Length', color_continuous_scale='Purples',
                          text_auto=True)
            fig3.update_layout(height=350)
            st.plotly_chart(fig3, use_container_width=True)

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("总简历数", len(df))
            col2.metric("岗位类别", df['Category'].nunique())
            col3.metric("平均长度", f"{int(df['text_len'].mean())} 字")
            col4.metric("最长简历", f"{int(df['text_len'].max())} 字")
        else:
            st.info("Kaggle 数据集未加载")

    elif dash_section == "优秀简历库":
        stats = collector.get_stats()
        st.markdown(f"**优秀简历库**: 共 {stats['total']} 份")
        cats = stats.get("categories", {})
        if cats:
            cat_df = pd.DataFrame([
                {"类别": k, "数量": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])
            ])
            fig4 = px.pie(cat_df, names='类别', values='数量',
                          title='优秀简历类别分布',
                          color_discrete_sequence=px.colors.sequential.Blues_r)
            fig4.update_traces(textposition='inside', textinfo='label+percent')
            fig4.update_layout(height=350)
            st.plotly_chart(fig4, use_container_width=True)

    elif dash_section == "面试记录分析":
        records_mgr = st.session_state.records_mgr
        rec_stats = records_mgr.get_stats()
        dim_stats = records_mgr.get_dimension_stats()

        if rec_stats["total"] == 0:
            st.info("暂无面试记录，请先到「批量测试」页面运行评估")
        else:
            # 总览指标
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("总评估次数", rec_stats["total"])
            r2.metric("覆盖岗位数", len(rec_stats["categories"]))
            avg = rec_stats.get("avg_scores", {}).get("overall", "-")
            r3.metric("平均综合分", avg if avg != "-" else "-")
            r4.metric("最高综合分", max(
                (r["scores"]["overall"] for r in records_mgr.get_records(999)
                 if r.get("scores", {}).get("overall")), default="-"))

            col_a, col_b = st.columns(2)

            with col_a:
                # 各岗位平均分对比
                by_cat = rec_stats.get("by_category", {})
                if by_cat:
                    cat_df = pd.DataFrame([
                        {"岗位类别": cat, "平均分": data["avg_overall"], "数量": data["count"]}
                        for cat, data in sorted(by_cat.items(), key=lambda x: -x[1]["avg_overall"])
                    ])
                    fig_cat = px.bar(cat_df, x="岗位类别", y="平均分",
                                     title="各岗位平均评分对比",
                                     color="平均分", color_continuous_scale="RdYlGn",
                                     text_auto=True, hover_data=["数量"])
                    fig_cat.update_layout(height=350, xaxis_tickangle=-45)
                    st.plotly_chart(fig_cat, use_container_width=True)

            with col_b:
                # 各维度平均分对比
                if dim_stats:
                    dim_df = pd.DataFrame(dim_stats)
                    fig_dim = px.bar(dim_df, x="label", y="avg",
                                     title="各评估维度平均分",
                                     color="avg", color_continuous_scale="Viridis",
                                     text_auto=True,
                                     labels={"label": "评估维度", "avg": "平均分"})
                    fig_dim.update_layout(height=350)
                    st.plotly_chart(fig_dim, use_container_width=True)

            # 维度箱线图
            st.markdown("**各维度评分分布**")
            records_list = records_mgr.get_records(999)
            if records_list:
                box_data = []
                for r in records_list:
                    scores = r.get("scores", {})
                    for dim_key, dim_label in [("skills_match", "技能匹配度"), ("project_quality", "项目经验质量"),
                                                ("format_readability", "格式与可读性"), ("education", "教育背景"),
                                                ("expression", "内容表达")]:
                        if scores.get(dim_key):
                            box_data.append({"维度": dim_label, "评分": scores[dim_key]})
                if box_data:
                    box_df = pd.DataFrame(box_data)
                    fig_box = px.box(box_df, x="维度", y="评分", color="维度",
                                     title="评估评分分布箱线图", points="all")
                    fig_box.update_layout(height=400)
                    st.plotly_chart(fig_box, use_container_width=True)

            # 全部记录明细
            with st.expander("查看所有记录明细"):
                all_recs = records_mgr.get_records(999)
                if all_recs:
                    detail_df = pd.DataFrame([
                        {
                            "时间": r.get("created_at", ""),
                            "岗位": r.get("category", ""),
                            "综合分": r.get("scores", {}).get("overall", ""),
                            "技能": r.get("scores", {}).get("skills_match", ""),
                            "项目": r.get("scores", {}).get("project_quality", ""),
                            "格式": r.get("scores", {}).get("format_readability", ""),
                            "教育": r.get("scores", {}).get("education", ""),
                            "表达": r.get("scores", {}).get("expression", ""),
                            "优势": ", ".join(r.get("strengths", [])),
                            "不足": ", ".join(r.get("weaknesses", [])),
                        }
                        for r in all_recs
                    ])
                    st.dataframe(detail_df, use_container_width=True, hide_index=True)

                    if st.button("🗑️ 清空所有记录"):
                        records_mgr.clear()
                        st.rerun()

st.markdown('</div>', unsafe_allow_html=True)
