"""简历解析模块 - 支持文本/PDF/DOCX/图片多模态输入"""

import os
import json
import tempfile
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

EXTRACT_PROMPT = """你是一位专业的简历分析师。请从以下简历文本中提取结构化信息，返回 JSON 格式。

请提取以下字段（如果没有则填 null）：
- name: 姓名
- education: 学历（博士/硕士/本科/专科）
- school: 毕业院校
- major: 专业
- skills: 技能列表 (array)
- work_experience: 工作经历列表，每项包含 {company, role, duration, description}
- projects: 项目经验列表，每项包含 {name, role, description, tech_stack, achievement}
- certifications: 证书列表
- target_position: 目标岗位

只返回 JSON，不要其他内容。"""


def extract_text_from_pdf(file_path: str) -> str:
    """从 PDF 提取文本（文本PDF直接提取，扫描PDF自动OCR兜底）"""
    try:
        import fitz
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        text = text.strip()
        # 文本不足 -> 可能是扫描件，触发 OCR
        if len(text) < 20:
            try:
                import easyocr
                reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                ocr_text = []
                import fitz as fz
                doc2 = fz.open(file_path)
                for page in doc2:
                    pix = page.get_pixmap(dpi=200)
                    img = pix.tobytes("png")
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        tmp.write(img)
                        tmp_path = tmp.name
                    try:
                        result = reader.readtext(tmp_path, detail=0)
                        ocr_text.extend(result)
                    finally:
                        import os
                        os.unlink(tmp_path)
                doc2.close()
                text = "\n".join(ocr_text)
            except ImportError:
                pass  # OCR 不可用时返回已提取的少量文本
        return text.strip()
    except ImportError:
        return "PDF解析库未安装，请安装 PyMuPDF"


def extract_text_from_docx(file_path: str) -> str:
    """从 Word 文档提取文本"""
    try:
        from docx import Document
        doc = Document(file_path)
        text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return text.strip()
    except ImportError:
        return "Word解析库未安装，请安装 python-docx"


def extract_text_from_image(file_path: str) -> str:
    """从图片提取文字（OCR）"""
    try:
        import easyocr
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)
        result = reader.readtext(file_path, detail=0)
        return "\n".join(result)
    except ImportError:
        # fallback to pytesseract
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(file_path)
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            return text.strip()
        except ImportError:
            return "OCR库未安装，请安装 easyocr 或 pytesseract"


def extract_structured_info(resume_text: str, api_key: str = None, base_url: str = None) -> dict:
    """用 LLM 从简历文本中提取结构化信息"""
    client = OpenAI(
        api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
        base_url=base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    resp = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": resume_text[:6000]},
        ],
        temperature=0.1,
        max_tokens=2048,
    )
    reply = resp.choices[0].message.content
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', reply, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"error": "解析失败", "raw": reply[:200]}


def detect_input_type(file_path: str) -> str:
    """检测文件类型"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return "pdf"
    elif ext in (".docx", ".doc"):
        return "docx"
    elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"):
        return "image"
    else:
        return "text"


def parse_resume(input_source: str, is_file: bool = False) -> dict:
    """统一入口：接收文本或文件路径，返回结构化简历"""
    if is_file:
        file_type = detect_input_type(input_source)
        if file_type == "pdf":
            text = extract_text_from_pdf(input_source)
        elif file_type == "docx":
            text = extract_text_from_docx(input_source)
        elif file_type == "image":
            text = extract_text_from_image(input_source)
        else:
            with open(input_source, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
    else:
        text = input_source

    info = extract_structured_info(text)
    return {
        "raw_text": text[:3000],
        "structured": info,
        "text_length": len(text),
    }
