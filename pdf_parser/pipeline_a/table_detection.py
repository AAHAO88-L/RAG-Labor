"""OpenCV-based table detection for Chinese document PDFs.

Strategy (two-stage):
  1. Morphological border detection — finds tables with visible grid lines
  2. Projection-profile fallback — detects borderless tables via row/column spacing

Both stages return bounding boxes that are then OCR'd by the pipeline processor.
"""

import cv2
import numpy as np
from itertools import groupby


def _nms(boxes, overlap_thresh=0.3):
    """Non-Maximum Suppression on [[x1,y1,x2,y2], ...] boxes."""
    if not boxes:
        return []
    arr = np.array(boxes, dtype=np.float32)
    x1 = arr[:, 0]
    y1 = arr[:, 1]
    x2 = arr[:, 2]
    y2 = arr[:, 3]

    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    idxs = np.argsort(y1)  # sort by top y

    keep = []
    while len(idxs) > 0:
        i = idxs[0]
        keep.append(i)
        if len(idxs) == 1:
            break
        xx1 = np.maximum(x1[i], x1[idxs[1:]])
        yy1 = np.maximum(y1[i], y1[idxs[1:]])
        xx2 = np.minimum(x2[i], x2[idxs[1:]])
        yy2 = np.minimum(y2[i], y2[idxs[1:]])

        w = np.maximum(0, xx2 - xx1 + 1)
        h = np.maximum(0, yy2 - yy1 + 1)
        overlap = (w * h) / area[idxs[1:]]
        idxs = idxs[1:][overlap <= overlap_thresh]

    return [boxes[i] for i in keep]


def _detect_bordered_tables(binary, min_w, min_h):
    """Detect tables with visible grid lines via morphological operations."""
    h, w = binary.shape[:2]

    # Horizontal line detection
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 20), 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, h_kernel, iterations=2)

    # Vertical line detection
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 20)))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, v_kernel, iterations=2)

    # Intersections = table grid
    grid = cv2.bitwise_and(h_lines, v_lines)
    grid_dilated = cv2.dilate(grid, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(grid_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for cnt in contours:
        cx, cy, cw, ch = cv2.boundingRect(cnt)
        if cw >= min_w and ch >= min_h:
            boxes.append([cx, cy, cx + cw, cy + ch])

    return _nms(boxes, overlap_thresh=0.3)


def _detect_borderless_tables(binary, existing_boxes, page_w, page_h):
    """Detect tables without visible borders using projection profiles.

    Works on regions NOT already covered by bordered-table boxes.
    Returns [[x1,y1,x2,y2], ...].
    """
    # Create mask: 1 = uncovered region
    mask = np.ones((page_h, page_w), dtype=np.uint8) * 255
    for x1, y1, x2, y2 in existing_boxes:
        cv2.rectangle(mask, (int(x1), int(y1)), (int(x2), int(y2)), 0, -1)

    masked_binary = cv2.bitwise_and(binary, binary, mask=mask)

    # Horizontal projection: count text pixels per row
    inv = 255 - masked_binary  # text = white (255)
    horz_proj = np.sum(inv, axis=1)  # per row
    horz_proj = horz_proj.astype(np.float64)

    # Smooth to find gaps
    gap_threshold = max(np.max(horz_proj) * 0.02, 5)
    is_gap = horz_proj < gap_threshold

    # Find continuous gap runs (rows without text)
    gap_runs = []
    for k, g in groupby(enumerate(is_gap), key=lambda x: x[1]):
        if k:
            indices = [i for i, _ in g]
            gap_runs.append((indices[0], indices[-1]))

    # Row gaps separate potential table rows. A table has at least 3 row gaps
    # forming 2+ data rows.  Look for non-gap bands between gaps.
    # Simple heuristic: take non-gap stretches that are tall enough (> 1.5× line height)
    non_gap_bands = []
    prev_end = -1
    for start, end in gap_runs:
        if start > prev_end + 1:
            non_gap_bands.append((prev_end + 1, start - 1))
        prev_end = end
    if prev_end < page_h - 1:
        non_gap_bands.append((prev_end + 1, page_h - 1))

    # For each non-gap band, check if it looks like a table:
    #  - Width of text spans most of page (> 40%)
    #  - Has consistent column gaps (vertical projection shows regular spacing)
    min_table_rows = 3
    min_table_cols = 2

    tables = []
    for band_start, band_end in non_gap_bands:
        band_h = band_end - band_start + 1
        if band_h < 30:
            continue
        band_region = inv[band_start:band_end + 1, :]
        # Vertical projection on band
        vert_proj = np.sum(band_region, axis=0).astype(np.float64)
        v_gap = vert_proj < np.max(vert_proj) * 0.02
        col_gap_count = 0
        for k, g in groupby(v_gap, key=lambda x: x):
            if k:
                col_gap_count += 1
        # If many column gaps, likely a table
        if col_gap_count >= min_table_cols:
            # Count rows: within band, detect sub-gaps
            sub_horz = np.sum(band_region, axis=1)
            sub_gap = sub_horz < np.max(sub_horz) * 0.02
            row_gap_count = 0
            for k, g in groupby(sub_gap, key=lambda x: x):
                if k:
                    row_gap_count += 1
            if row_gap_count >= min_table_rows:
                tables.append([0, band_start, page_w - 1, band_end])

    return tables


def detect_tables(image, min_width_ratio=0.15, min_height_ratio=0.05):
    """Detect table regions in a page image.

    Args:
        image: numpy RGB array (H, W, 3).
        min_width_ratio: minimum table width as fraction of page width.
        min_height_ratio: minimum table height as fraction of page height.

    Returns:
        List of {"bbox": [x1, y1, x2, y2]}.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    min_w = int(w * min_width_ratio)
    min_h = int(h * min_height_ratio)

    # Stage 1: bordered tables
    bordered = _detect_bordered_tables(binary, min_w, min_h)

    # Stage 2: borderless tables (on uncovered regions)
    borderless = _detect_borderless_tables(binary, bordered, w, h)
    all_boxes = bordered + borderless

    return [{"bbox": box} for box in _nms(all_boxes, overlap_thresh=0.4)]
