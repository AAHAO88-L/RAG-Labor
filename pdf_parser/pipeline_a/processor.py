"""Pipeline A orchestrator — per-page text/table extraction.

For each page:
  1. Render page as image (300 DPI by default)
  2. Run OpenCV table detection → table bboxes
  3. Run PaddleOCR → full-page text + bboxes
  4. Classify OCR results as heading / text / table-contents
  5. Return sorted block list
"""

import logging

from pdf_parser.pipeline_a.page_image import pdf_to_images
from pdf_parser.pipeline_a.table_detection import detect_tables
from pdf_parser.pipeline_a.ocr import detect_text, recognize_crop

logger = logging.getLogger(__name__)


def _is_table_text(bbox, table_boxes):
    """Check if a text bbox overlaps significantly with any table region."""
    tx1, ty1, tx2, ty2 = bbox
    for tb in table_boxes:
        bx1, by1, bx2, by2 = tb["bbox"]
        # IoU check — if center of text lies inside table → it belongs to the table
        cx = (tx1 + tx2) / 2
        cy = (ty1 + ty2) / 2
        if bx1 <= cx <= bx2 and by1 <= cy <= by2:
            return True
    return False


def _extract_table_content(page_image, table_boxes):
    """Crop and OCR each table region, return as structured markdown strings."""
    tables = []
    for tb in table_boxes:
        x1, y1, x2, y2 = [int(v) for v in tb["bbox"]]
        crop = page_image[y1:y2, x1:x2]
        # Recognize text within the table crop
        cells = detect_text(crop)

        # Group by y (row), sort by x (col)
        if not cells:
            tables.append({"bbox": tb["bbox"], "content": "", "rows": 0, "cols": 0})
            continue

        # Simple row grouping: texts whose y-centers are within 15px of each other
        rows = []
        row_thresh = 15
        sorted_cells = sorted(cells, key=lambda c: (c["bbox"][1], c["bbox"][0]))
        current_row = [sorted_cells[0]]
        for c in sorted_cells[1:]:
            cy = (c["bbox"][1] + c["bbox"][3]) / 2
            prev_cy = (current_row[-1]["bbox"][1] + current_row[-1]["bbox"][3]) / 2
            if abs(cy - prev_cy) <= row_thresh:
                current_row.append(c)
            else:
                rows.append(current_row)
                current_row = [c]
        if current_row:
            rows.append(current_row)

        # Build markdown table
        md_lines = []
        for ri, row in enumerate(rows):
            row.sort(key=lambda c: c["bbox"][0])
            row_texts = [c["text"] for c in row]
            md_lines.append("| " + " | ".join(row_texts) + " |")
            if ri == 0:
                md_lines.append("|" + "---|" * len(row))

        tables.append({
            "bbox": tb["bbox"],
            "content": "\n".join(md_lines),
            "rows": len(rows),
            "cols": max((len(r) for r in rows), default=0),
        })
    return tables


def _classify_block(text, bbox, page_width, page_height):
    """Heuristic classification: heading vs text.

    A block is a heading if:
      - It's near the top of the page (y < 15% of page height)
      - OR it's short and centered (x_start > 30% of width, x_end < 70% of width)
      - OR it contains common heading markers like "第" + "章/节"
    """
    x1, y1, x2, y2 = bbox
    text_stripped = text.strip()

    is_short = len(text_stripped) < 30
    is_top = y1 < page_height * 0.15
    is_centered = (x1 > page_width * 0.25) and (x2 < page_width * 0.75)
    has_chapter_marker = any(kw in text_stripped for kw in ["第", "章", "节", "部分"])

    if has_chapter_marker and is_short:
        return "heading"
    if is_top and is_short and is_centered:
        return "heading"
    return "text"


def process_page(page_image, page_w, page_h, device="cpu"):
    """Extract blocks from a single page image.

    Args:
        page_image: numpy RGB array.
        page_w: page width in points (for bbox reference).
        page_h: page height in points.
        device: "cpu" or "cuda".

    Returns:
        list of Block dicts.
    """
    # 1. Table detection
    table_boxes = detect_tables(page_image)
    logger.debug("  Page: %d tables detected", len(table_boxes))

    # 2. Extract table content
    tables = _extract_table_content(page_image, table_boxes)

    # 3. Full-page OCR
    ocr_boxes = detect_text(page_image, device=device)
    logger.debug("  Page: %d OCR text boxes", len(ocr_boxes))

    # 4. Classify & filter (remove text inside tables)
    blocks = []
    for ob in ocr_boxes:
        if _is_table_text(ob["bbox"], table_boxes):
            continue  # belongs to a table, skip
        block_type = _classify_block(ob["text"], ob["bbox"], page_w, page_h)
        blocks.append({
            "type": block_type,
            "bbox": ob["bbox"],
            "content": ob["text"],
            "confidence": ob["confidence"],
            "rows": None,
            "cols": None,
            "figure_file": None,
            "alt_text": None,
        })

    # 5. Add table blocks
    for t in tables:
        blocks.append({
            "type": "table",
            "bbox": t["bbox"],
            "content": t["content"],
            "confidence": 0.85,
            "rows": t["rows"],
            "cols": t["cols"],
            "figure_file": None,
            "alt_text": None,
        })

    # 6. Sort top-to-bottom by y-center
    blocks.sort(key=lambda b: (b["bbox"][1] + b["bbox"][3]) / 2)
    return blocks


def parse_pdf(filepath: str, dpi: int = 300, device: str = "cpu"):
    """Full Pipeline A parse of a PDF file.

    Args:
        filepath: Path to PDF file.
        dpi: Page rendering DPI.
        device: "cpu" or "cuda".

    Returns:
        {"filename": ..., "total_pages": N, "pages": [{"page_num":..., "blocks":[...]}, ...]}
    """
    import os

    result = {"filename": os.path.basename(filepath), "total_pages": 0, "pages": []}

    for page_num, (img, pw, ph) in enumerate(pdf_to_images(filepath, dpi=dpi), start=1):
        logger.info("Processing page %d ...", page_num)
        blocks = process_page(img, pw, ph, device=device)
        result["pages"].append({
            "page_num": page_num,
            "width": pw,
            "height": ph,
            "blocks": blocks,
        })
        result["total_pages"] = page_num

    return result
