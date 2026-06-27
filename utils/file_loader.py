"""文件加载器 — 支持 PDF、DOCX、TXT 格式"""

import os

def load_file(filepath):
    """加载单个文件，返回文本内容。"""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return _load_pdf(filepath)
    elif ext == '.docx':
        return _load_docx(filepath)
    elif ext in ('.txt', '.md'):
        return _load_txt(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def load_file_structured(filepath, parser_url=None, mode="lightweight"):
    """使用 PDF 解析微服务加载 PDF，返回结构化 JSON（含 text/table/figure blocks）。

    仅对 PDF 生效，非 PDF 文件回退到 load_file() 返回文本。
    需要 PDF_PARSER_URL 环境变量指向 pdf-parser 服务。

    Returns:
        dict {"filename", "total_pages", "pages"} 或 plain text str（非 PDF 时）。
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext != ".pdf":
        return load_file(filepath)

    import requests as _req
    url = parser_url or os.getenv("PDF_PARSER_URL", "http://pdf-parser:8001")

    with open(filepath, "rb") as f:
        resp = _req.post(
            f"{url}/api/v1/parse",
            files={"file": (os.path.basename(filepath), f, "application/pdf")},
            params={"mode": mode},
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()

def load_files_from_folder(folder):
    """读取 folder 下的 PDF/DOCX/TXT/MD 文件，返回 {path: text} 的字典"""
    results = {}
    if not os.path.exists(folder):
        return results
    for root, _, files in os.walk(folder):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in ('.pdf', '.docx', '.txt', '.md'):
                continue
            path = os.path.join(root, name)
            try:
                results[path] = load_file(path)
            except Exception as e:
                print(f"  [WARN] 读取失败 {name}: {e}")
    return results


def _load_txt(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def _load_pdf(filepath):
    """多引擎 PDF 文本提取（页面级混合模式）。

    对每一页独立处理：
    1. pdfplumber 提取文本——足够则用
    2. PyMuPDF 提取文本——pdfplumber 失败时回退
    3. OCR 识别——前两者提取不足时（图片页）兜底

    文字页走提取，图片页走 OCR，自然支持图文混排。
    """

    import logging
    logger = logging.getLogger(__name__)
    MIN_TEXT_LEN = 20  # 一页少于这个字符数则认为该页是图片页

    # ── 页面级提取：先尝试文本引擎，不足则 OCR ──
    def _extract_page_text(page, fitz_page=None, page_idx=0):
        """对单页尝试文本提取，返回 (页面文本, 是否使用了OCR)。"""
        text = ""

        # 引擎 1：pdfplumber
        try:
            import pdfplumber
            if page.chars:
                text = page.dedupe_chars().get_text() or page.extract_text() or ""
            else:
                text = page.extract_text() or ""
        except Exception:
            pass

        # 引擎 2：PyMuPDF 回退
        if len(text.strip()) < MIN_TEXT_LEN and fitz_page is not None:
            try:
                text = fitz_page.get_text() or ""
            except Exception:
                pass

        # 引擎 3：OCR 兜底
        if len(text.strip()) < MIN_TEXT_LEN:
            try:
                import pytesseract
                from PIL import Image
                if fitz_page is not None:
                    pix = fitz_page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_text = pytesseract.image_to_string(img, lang="chi_sim+eng")
                    if ocr_text.strip():
                        logger.info("  第 %d 页 OCR 识别", page_idx + 1)
                        return ocr_text.strip(), True
            except ImportError:
                pass
            except Exception:
                logger.warning("  第 %d 页 OCR 失败", page_idx + 1, exc_info=True)

        return text.strip(), False

    # ── 主流程 ──
    try:
        import pdfplumber
        import fitz
    except ImportError:
        pass  # 降级到末尾的纯 fitz 兜底

    pages_text = []
    used_ocr_any = False

    try:
        fitz_doc = fitz.open(filepath)
        with pdfplumber.open(filepath) as pdf:
            for i, (plumb_page, fitz_pg) in enumerate(zip(pdf.pages, fitz_doc)):
                text, used_ocr = _extract_page_text(plumb_page, fitz_pg, i)
                if used_ocr:
                    used_ocr_any = True
                pages_text.append(text)
        fitz_doc.close()

        result = "\n".join(pages_text).strip()
        if result:
            if used_ocr_any:
                logger.info("部分页面使用了 OCR 识别")
            return result
    except Exception:
        logger.warning("pdfplumber+fitz 混合提取失败，降级到纯 fitz", exc_info=True)
        try:
            fitz_doc.close()
        except Exception:
            pass

    # ── 降级：纯 PyMuPDF ──
    try:
        import fitz
        doc = fitz.open(filepath)
        texts = [page.get_text() for page in doc]
        doc.close()
        result = "\n".join(texts).strip()
        if result:
            return result
    except Exception:
        logger.warning("PyMuPDF 提取失败", exc_info=True)

    # ── 最终降级：全文 OCR ──
    try:
        import pytesseract
        from pdf2image import convert_from_path
        images = convert_from_path(filepath, dpi=300)
        ocr_text = "\n".join(pytesseract.image_to_string(img, lang="chi_sim+eng") for img in images)
        ocr_text = ocr_text.strip()
        if ocr_text:
            logger.info("全文档 OCR 识别完成")
            return ocr_text
    except ImportError:
        logger.warning(
            "所有文本引擎均无法提取内容，可安装 OCR 依赖兜底："
            "pip install pytesseract pdf2image，并安装 tesseract-ocr"
        )
    except Exception:
        logger.warning("全文 OCR 失败", exc_info=True)

    return ""


def _load_docx(filepath):
    """使用 python-docx 解析 DOCX"""
    from docx import Document
    doc = Document(filepath)
    return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
