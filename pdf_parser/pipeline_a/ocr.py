"""PaddleOCR wrapper for Chinese text recognition.

Lazy-loads the model on first call to keep the server start-up fast.
"""

import logging

logger = logging.getLogger(__name__)

_ocr = None


def _get_engine(device="cpu"):
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR

        logger.info("Loading PaddleOCR (lang=ch, device=%s) ...", device)
        _ocr = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            use_gpu=(device == "cuda"),
            show_log=False,
            det_db_thresh=0.3,
            det_db_box_thresh=0.5,
        )
        logger.info("PaddleOCR loaded.")
    return _ocr


def detect_text(image, device="cpu"):
    """Run PaddleOCR on a full-page image.

    Args:
        image: numpy array (H, W, 3) RGB.
        device: "cpu" or "cuda".

    Returns:
        List of {"bbox": [x1,y1,x2,y2], "text": str, "confidence": float}
        sorted top-to-bottom, left-to-right within each row.
    """
    engine = _get_engine(device)
    result = engine.ocr(image, cls=True)
    if not result or not result[0]:
        return []

    boxes = []
    for line in result[0]:
        pts, (text, conf) = line
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append(
            {
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "text": text,
                "confidence": conf,
            }
        )

    # Sort top-to-bottom then left-to-right
    boxes.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return boxes


def recognize_crop(crop_image, device="cpu"):
    """Recognize text from a cropped image region.

    Args:
        crop_image: numpy array (H, W, 3) RGB.
        device: "cpu" or "cuda".

    Returns:
        (text, confidence) or ("", 0.0) if nothing found.
    """
    engine = _get_engine(device)
    result = engine.ocr(crop_image, cls=True)
    if not result or not result[0]:
        return "", 0.0

    texts = []
    confs = []
    for line in result[0]:
        _, (text, conf) = line
        texts.append(text)
        confs.append(conf)

    return " ".join(texts), sum(confs) / len(confs) if confs else 0.0
