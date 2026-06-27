"""pdf_parser configuration — loaded from environment variables."""

import os
from dotenv import load_dotenv

# Try to load .env from the project root
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path=_env_path, override=True)


def load_config():
    return {
        "host": os.getenv("PDF_PARSER_HOST", "0.0.0.0"),
        "port": int(os.getenv("PDF_PARSER_PORT", "8001")),
        # Pipeline A
        "pipeline_a_device": os.getenv("PIPELINE_A_DEVICE", "cpu"),
        "ocr_lang": os.getenv("OCR_LANG", "ch"),
        "table_min_width_ratio": float(os.getenv("TABLE_MIN_WIDTH_RATIO", "0.15")),
        "table_min_height_ratio": float(os.getenv("TABLE_MIN_HEIGHT_RATIO", "0.05")),
        "page_dpi": int(os.getenv("PAGE_DPI", "300")),
        # Pipeline B (placeholder for Phase 2)
        "pipeline_b_device": os.getenv("PIPELINE_B_DEVICE", "cpu"),
        "multimodal_llm_api_key": os.getenv("MULTIMODAL_LLM_API_KEY", ""),
        "multimodal_llm_api_url": os.getenv("MULTIMODAL_LLM_API_URL", ""),
        "multimodal_llm_model": os.getenv("MULTIMODAL_LLM_MODEL", "qwen-vl-plus"),
        "figure_storage_dir": os.getenv("FIGURE_STORAGE_DIR", "/tmp/figures"),
    }
