# AI Mock Interview — 智能模拟面试系统

基于 **Multi-Agent 架构** 的简历评估与模拟面试系统。输入简历 → AI 全流程分析（评估/润色/面试）→ 输出结构化报告。

> 大数据分析课程项目

---

## 架构（v2.0 — Multi-Agent 协同）

```
                         ┌──────────────────────────────────┐
                         │         AgentCoordinator          │
                         │  (三级路由: 关键词预检→LLM→反问)   │
                         └────┬──────────┬──────────┬───────┘
                              │          │          │
                    ┌─────────┘  ┌───────┘  ┌──────┘
                    ▼            ▼           ▼
            ┌────────────┐ ┌──────────┐ ┌────────────┐
            │AnalysisAgent│ │Evaluation│ │Interview   │
            │  分析Agent  │ │ Agent    │ │ Agent      │
            │             │ │ 评估Agent│ │ 面试Agent  │
            │ · 解析简历  │ │ · 多维度 │ │ · 开始面试 │
            │ · 查询知识库│ │   评分   │ │ · 对话     │
            │ · 润色简历  │ │ · 简历采集│ │ · 结束面试 │
            └────────────┘ └──────────┘ └────────────┘
                    │              │              │
                    ▼              ▼              ▼
            ┌──────────────────────────────────────────┐
            │              工具模块层                    │
            │  resume_parser / resume_evaluator /       │
            │  knowledge_base / resume_polisher /       │
            │  resume_collector / interview_session      │
            └──────────────────────────────────────────┘
```

**三层分离**：UI 层（Streamlit）→ 编排层（AgentCoordinator + 3 个专业化 Agent）→ 工具层（独立模块），每层只依赖下一层。

### 与 v1.0 的主要区别

| v1.0（单 WorkflowAgent） | v2.0（多 Agent 协同） |
|--------------------------|----------------------|
| 一个 Agent 管所有事 | 3 个专业 Agent + Coordinator 编排 |
| 只有 LLM function calling 路由 | 三级路由（关键词预检→LLM→反问兜底） |
| 单次评分 | Multi-shot N=3 + 95% 置信区间 |
| 单一评分标准 | 国内/国际双标准自动切换 |

---

## 功能

| 功能 | 说明 |
|------|------|
| **多格式简历输入** | 支持粘贴文本、上传 PDF/DOCX/图片（OCR） |
| **AI 简历评估** | 5 维度加权评分（技能30%/项目25%/格式15%/教育15%/表达15%）+ 同类对比 |
| **Multi-shot 置信区间** | 调用 N=3 次 LLM，计算均值 ± 95% CI，解决单次评分波动问题 |
| **双标准切换** | 自动识别中英文简历，国内宽松 vs 国际严格标准 |
| **模拟面试** | 基于评估弱项的个性化面试 + 流式逐字输出 + 面试报告 |
| **简历润色** | AI 优化表达、量化成果、STAR 法则 + 流式进度 |
| **知识库** | Kaggle 962 份简历（25 个岗位类别）+ 16 份优秀简历 |
| **AI 助手** | 自然语言输入，三级路由自动分配到对应 Agent |
| **数据看板** | 数据集分布、技能词频分析、评分验证对比 |
| **会话持久化** | 页面刷新自动恢复进度 |

---

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

创建 `.env` 文件：

```
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 运行数据分析（首次运行前执行）

```bash
python modules/data_analysis.py
python modules/scoring_validation.py
```

### 4. 启动系统

```bash
streamlit run app.py
```

打开 http://localhost:8501

---

## 数据

- **Kaggle 数据集**：`data/UpdatedResumeDataSet.csv` — 962 份简历，25 个岗位类别
- **优秀简历库**：`modules/resume_collector.py` — 16 份真实案例，8 个类别
- **分析缓存**：`data/analysis_cache.json` — 技能关键词、词频统计等分析结果
- **验证缓存**：`data/validation_cache.json` — 单次 vs Multi-shot 评分对比实验数据
- **会话备份**：`data/session_backup.json` — 自动保存，刷新恢复

---

## 数据分析

基于 Kaggle 962 份简历的文本挖掘，得出以下结论：

### 技能分布 Top 10

| 技能 | 出现次数 | 覆盖率 |
|------|---------|--------|
| SQL | 478 | 50% |
| Testing | 373 | 39% |
| Java | 335 | 35% |
| Web | 331 | 34% |
| JavaScript | 301 | 31% |
| Cloud | 233 | 24% |
| BigData | 181 | 19% |
| Python | 176 | 18% |
| DevOps | 172 | 18% |
| ML/AI | 108 | 11% |

### 评分验证结论

从 5 个不同岗位各取 1 份简历，分别用单次评分和 Multi-shot（N=3）评估：

- 单次评分与 3 次均值的差值在 0-7 分之间，说明单次评分存在波动
- 95% CI 大小反映 LLM 对简历的确定程度（CI 大 → 建议人工复核）
- Multi-shot 能有效平滑单次异常波动，评分更稳定

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Streamlit, Plotly |
| 编排层 | AgentCoordinator + 3 x Agent (LLMClient + Function Calling) |
| LLM | DeepSeek Chat (OpenAI 兼容) |
| 解析 | PyMuPDF (PDF), python-docx (DOCX), easyOCR (图片) |
| 数据分析 | Pandas, Plotly, 文本挖掘 |
| 数据 | Pandas (Kaggle), JSON (优秀简历库) |

---

## 项目结构

```
├── app.py                         # 主入口（Streamlit 页面）
├── modules/
│   ├── agent_base.py              # BaseAgent 抽象基类
│   ├── agent_workflow.py          # 向后兼容桥接层
│   ├── coordinator.py             # AgentCoordinator（核心编排器）
│   ├── analysis_agent.py          # 分析 Agent（解析/知识库/润色）
│   ├── evaluation_agent.py        # 评估 Agent（评分/采集）
│   ├── interview_agent.py         # 面试 Agent
│   ├── llm_client.py              # LLM 统一调用接口
│   ├── resume_parser.py           # 简历解析（PDF/DOCX/图片OCR）
│   ├── resume_evaluator.py        # 简历评估引擎（5维度+CI）
│   ├── knowledge_base.py          # 知识库（Kaggle + 优秀简历）
│   ├── resume_collector.py        # 简历采集
│   ├── resume_polisher.py         # 简历润色
│   ├── record_manager.py          # 面试记录管理
│   ├── data_analysis.py           # 数据分析（技能提取/词频）
│   └── scoring_validation.py      # 评分验证（单次 vs Multi-shot）
├── utils/
│   ├── file_utils.py              # 文件上传工具
│   └── config.py                  # 权重配置
├── styles/
│   └── style.css                  # UI 样式
├── data/
│   ├── UpdatedResumeDataSet.csv   # Kaggle 数据集
│   ├── excellent_resumes.json     # 优秀简历库
│   ├── interview_records.json     # 面试记录
│   ├── analysis_cache.json        # 数据分析缓存
│   └── validation_cache.json      # 评分验证缓存
├── tests/                         # 单元测试（193 tests）
│   ├── test_agent_base.py         # BaseAgent 抽象基类测试
│   ├── test_analysis_agent.py     # 分析 Agent 测试
│   ├── test_coordinator.py        # 协调器路由 & Pipeline 测试
│   ├── test_evaluation_agent.py   # 评估 Agent 测试
│   ├── test_evaluator.py          # 评估引擎测试
│   ├── test_interview_agent.py    # 面试 Agent & Session 测试
│   ├── test_knowledge_base.py     # 知识库测试
│   ├── test_record_manager.py     # 记录管理测试
│   ├── test_resume_polisher.py    # 润色模块测试
│   └── test_utils.py              # 配置验证测试
├── .gitignore
├── requirements.txt
└── run.bat                        # 一键启动脚本
```
