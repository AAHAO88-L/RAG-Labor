"""FastAPI app — PDF Parser Microservice.

Endpoints:
  POST /api/v1/parse  — Pipeline A: extract text/tables with structure
  GET  /health        — health check
"""

import os
import logging
import tempfile

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pdf_parser.config import load_config
from pdf_parser.schemas import ParseResult, Page, Block

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

cfg = load_config()
app = FastAPI(title="PDF Parser", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXT = {".pdf"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/parse", response_model=ParseResult)
async def parse_pdf(
    file: UploadFile = File(...),
    mode: str = "lightweight",
):
    """Parse a PDF with Pipeline A (lightweight mode).

    - mode="lightweight": OpenCV table detection + PaddleOCR (Pipeline A)
    - mode="full": (not yet implemented, Phase 2) also runs layout analysis + alt text
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}, only PDF supported")

    if mode not in ("lightweight", "full"):
        raise HTTPException(status_code=400, detail="mode must be 'lightweight' or 'full'")

    # Save uploaded file to temp
    tmp_dir = tempfile.mkdtemp(prefix="pdf_parser_")
    tmp_path = os.path.join(tmp_dir, file.filename or f"upload{ext}")
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        if mode == "full":
            # TODO: Phase 2 — Pipeline B layout analysis + alt text generation
            raise HTTPException(status_code=501, detail="Full mode (Pipeline B) not yet implemented")

        # Run Pipeline A
        from pdf_parser.pipeline_a.processor import parse_pdf as run_pipeline_a
        result = run_pipeline_a(
            tmp_path,
            dpi=cfg["page_dpi"],
            device=cfg["pipeline_a_device"],
        )
        return ParseResult(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF parse failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Parse failed: {e}")
    finally:
        # Cleanup
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass
