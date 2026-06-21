"""API Server — 为独立前端提供 REST 接口"""
import os, sys, json, hashlib, uuid, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(title="AI Resume System API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ========== Modules (lazy loaded) ==========
_kb = None
_coordinator = None

def get_kb():
    global _kb
    if _kb is None:
        from modules.knowledge_base import ResumeKnowledgeBase
        _kb = ResumeKnowledgeBase()
    return _kb

def get_coordinator():
    global _coordinator
    if _coordinator is None:
        from modules.coordinator import AgentCoordinator
        _coordinator = AgentCoordinator()
    return _coordinator

# ========== Models ==========
class EvalRequest(BaseModel):
    resume_text: str
    category: str = "未指定"

class ChatRequest(BaseModel):
    message: str
    history: list = []

class BatchRequest(BaseModel):
    category: str = "全部"
    count: int = 10

class InterviewStartRequest(BaseModel):
    resume_text: str
    category: str

class InterviewChatRequest(BaseModel):
    session_id: str
    message: str

class InterviewEndRequest(BaseModel):
    session_id: str

# ========== Interview Sessions (in-memory) ==========
_interview_sessions = {}
_interview_lock = threading.RLock()
_SESSION_TTL_SECONDS = 3600  # 1 小时后过期自动清理

def _cleanup_expired_sessions():
    """清理过期面试会话"""
    now = time.time()
    with _interview_lock:
        expired = [sid for sid, s in _interview_sessions.items()
                   if now - s.get("_created_at", now) > _SESSION_TTL_SECONDS]
        for sid in expired:
            del _interview_sessions[sid]
    if expired:
        print(f"[API] 清理 {len(expired)} 个过期面试会话")

# ========== Data Endpoints ==========
@app.get("/api/experiments")
def get_experiments():
    path = os.path.join(DATA_DIR, "blind_experiment.json")
    if not os.path.exists(path):
        return {"experiments": []}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    summary = []
    for exp in data:
        hs = exp.get("human_score", {})
        aib = exp.get("ai_score_blind", {})
        aif = exp.get("ai_score_full", {})
        dims = aib.get("details", {}).get("dimensions", [])
        summary.append({
            "id": exp.get("id"),
            "category": exp.get("category"),
            "human": hs.get("midpoint") if hs else None,
            "human_range": f"{hs.get('range_lo')}-{hs.get('range_hi')}" if hs else None,
            "ai_blind": aib.get("overall"),
            "ai_full": aif.get("overall"),
            "dimensions": [{"label": d["label"], "score": d["score"], "color": d.get("color", "#888")} for d in dims],
        })
    return {"experiments": summary}

@app.get("/api/config/dimensions")
def get_dimensions():
    from utils.config import EVAL_WEIGHTS
    return {"dimensions": EVAL_WEIGHTS}

@app.get("/api/config/weights")
def get_weights():
    from utils.config import EVAL_WEIGHTS
    total = sum(v["weight"] for v in EVAL_WEIGHTS.values())
    return {"weights": EVAL_WEIGHTS, "total": total}

@app.get("/api/kaggle/stats")
def kaggle_stats():
    try:
        from modules.double_blind_experiment import _read_kaggle_csv
        df = _read_kaggle_csv()
        cats = df["Category"].value_counts().to_dict()
        return {
            "total": len(df),
            "categories": len(cats),
            "avg_length": int(df["Resume"].str.len().mean()),
            "cat_distribution": {k: int(v) for k, v in sorted(cats.items(), key=lambda x: -x[1])},
        }
    except Exception as e:
        return {"error": str(e)}

# ========== AI Endpoints ==========
@app.post("/api/evaluate")
def evaluate(req: EvalRequest):
    try:
        coordinator = get_coordinator()
        result = coordinator.evaluation_agent.execute_tool(
            "evaluate_resume", resume_text=req.resume_text, category=req.category)
        if "error" in result:
            return {"error": result.get("error_message", str(result.get("error", "未知错误")))}
        return {
            "overall": result.get("overall"),
            "weighted_score": result.get("weighted_score"),
            "overall_ci": result.get("overall_ci"),
            "dimensions": [
                {"key": d["key"], "label": d["label"], "score": d["score"],
                 "ci": d["ci"], "weight": d["weight"], "color": d["color"]}
                for d in result.get("dimensions", [])
            ],
            "strengths": result.get("strengths", []),
            "weaknesses": result.get("weaknesses", []),
            "summary": result.get("summary", ""),
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        coordinator = get_coordinator()
        context = {"history": req.history} if req.history else None
        result = coordinator.process_user_request(req.message, context)
        if result.get("type") == "text":
            return {"reply": result.get("content", "")}
        elif result.get("type") == "tool_calls":
            # 提取工具调用结果中的文本信息
            calls = result.get("calls", [])
            parts = []
            for c in calls:
                r = c.get("result", {})
                if c["tool"] == "evaluate_resume":
                    parts.append(f"综合评分: {r.get('overall', '?')}/100")
                    for d in r.get("dimensions", []):
                        parts.append(f"  {d['label']}: {d['score']}分")
                elif c["tool"] == "polish_resume":
                    parts.append(r.get("polished", "润色完成"))
                elif c["tool"] == "knowledge_lookup":
                    parts.append(f"找到 {r.get('count', 0)} 个样本")
                elif c["tool"] == "parse_resume":
                    parts.append("简历解析完成")
                elif c["tool"] == "start_interview":
                    parts.append(r.get("question", "面试已开始"))
                else:
                    parts.append(str(r)[:500])
            return {"reply": "\n\n".join(parts) if parts else "操作完成"}
        return {"reply": "抱歉，无法处理您的请求"}
    except Exception as e:
        return {"reply": f"抱歉，出现错误：{str(e)}"}

@app.post("/api/polish")
def polish(req: EvalRequest):
    try:
        coordinator = get_coordinator()
        result = coordinator.analysis_agent.execute_tool(
            "polish_resume", resume_text=req.resume_text, category=req.category)
        if "error" in result:
            return {"error": result.get("error_message", str(result.get("error", "润色失败")))}
        return result
    except Exception as e:
        return {"error": str(e)}

# ========== Batch Evaluation Endpoint ==========
@app.post("/api/batch")
def batch_evaluate(req: BatchRequest):
    try:
        kb = get_kb()
        df = kb.kaggle_df
        if df is None:
            return {"error": "数据集未加载"}

        if req.category and req.category != "全部":
            subset = df[df["Category"] == req.category]
        else:
            subset = df

        count = min(req.count, len(subset))
        sampled = subset.sample(n=count)
        coordinator = get_coordinator()  # 确保 Agent 在线程池之前初始化
        results = []
        errors = 0

        from concurrent.futures import ThreadPoolExecutor, as_completed
        samples_list = list(sampled.iterrows())
        results = [None] * len(samples_list)
        completed = 0
        _lock = threading.Lock()

        def _evaluate_one(idx, row):
            try:
                result = coordinator.evaluation_agent.execute_tool(
                    "evaluate_resume", resume_text=row["Resume"], category=row["Category"])
                if "error" in result:
                    return idx, None
                dims = {d["key"]: d["score"] for d in result.get("dimensions", [])}
                return idx, {
                    "category": row["Category"],
                    "overall": result.get("overall", 0),
                    "dimensions": dims,
                    "strengths": result.get("strengths", [])[:2],
                    "weaknesses": result.get("weaknesses", [])[:2],
                    "summary": result.get("summary", "")[:200],
                }
            except Exception:
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
                except Exception:
                    with _lock:
                        errors += 1
                        completed += 1

        valid = [r for r in results if r is not None]
        return {"results": valid, "total": len(valid), "errors": errors}
    except Exception as e:
        return {"error": str(e)}

# ========== Interview Endpoints ==========
@app.post("/api/interview/start")
def interview_start(req: InterviewStartRequest):
    try:
        coordinator = get_coordinator()

        # Evaluate resume via EvaluationAgent
        eval_result = coordinator.evaluation_agent.execute_tool(
            "evaluate_resume", resume_text=req.resume_text, category=req.category)

        # Start interview session (direct creation for multi-user support)
        from modules.interview_agent import InterviewSession
        session = InterviewSession(req.resume_text, eval_result, llm_client=coordinator.evaluation_agent.llm)
        first_q = session.start()

        session_id = str(uuid.uuid4())
        with _interview_lock:
            _cleanup_expired_sessions()
            session._created_at = time.time()
            _interview_sessions[session_id] = session

        return {
            "session_id": session_id,
            "question": first_q,
            "evaluation": {
                "overall": eval_result.get("overall"),
                "dimensions": [
                    {"key": d["key"], "label": d["label"], "score": d["score"],
                     "color": d.get("color", "#888")}
                    for d in eval_result.get("dimensions", [])
                ],
                "strengths": eval_result.get("strengths", []),
                "weaknesses": eval_result.get("weaknesses", []),
            }
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/interview/chat")
def interview_chat(req: InterviewChatRequest):
    with _interview_lock:
        _cleanup_expired_sessions()
        session = _interview_sessions.get(req.session_id)
    if not session:
        return {"error": "面试会话不存在或已过期"}
    try:
        reply = session.chat(req.message)
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/interview/end")
def interview_end(req: InterviewEndRequest):
    with _interview_lock:
        _cleanup_expired_sessions()
        session = _interview_sessions.pop(req.session_id, None)
    if not session:
        return {"error": "面试会话不存在或已过期"}
    try:
        report = session.end_interview()
        return report
    except Exception as e:
        return {"error": str(e)}

# ========== File Upload / OCR Endpoint ==========
import tempfile

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload file (txt/pdf/docx/png/jpg) → extract text via OCR/parser"""
    try:
        ext = os.path.splitext(file.filename or "upload.txt")[1].lower()
        content = await file.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            if ext == ".pdf":
                from modules.resume_parser import extract_text_from_pdf
                text = extract_text_from_pdf(tmp_path)
            elif ext in (".docx", ".doc"):
                from modules.resume_parser import extract_text_from_docx
                text = extract_text_from_docx(tmp_path)
            elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
                from modules.resume_parser import extract_text_from_image
                text = extract_text_from_image(tmp_path)
            else:
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
        finally:
            os.unlink(tmp_path)

        if not text or len(text.strip()) < 10:
            return {"error": "未能从文件中提取到有效文本，请尝试粘贴文本方式"}

        return {"text": text.strip(), "filename": file.filename, "length": len(text.strip())}
    except ImportError as e:
        return {"error": f"缺少 OCR/解析依赖: {str(e)}，请先安装所需包"}
    except Exception as e:
        return {"error": f"文件处理失败: {str(e)}"}

# ========== Static Files (fallback route, not mounted at /) ==========
frontend_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

_cache_headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

@app.get("/")
@app.get("/{path:path}")
def serve_frontend(path: str = ""):
    """Serve index.html for all non-API routes (SPA fallback)"""
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html", headers=_cache_headers)
    return JSONResponse({"error": "Frontend not found"}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
