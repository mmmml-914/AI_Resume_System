"""文件上传工具 — 统一处理 PDF/DOCX/图片/文本文件的解析"""

import os
import tempfile


def extract_text_from_upload(uploaded_file) -> str:
    """统一入口：接收 Streamlit UploadedFile，返回提取的文本"""
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(uploaded_file.getvalue())
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
    return text.strip()
