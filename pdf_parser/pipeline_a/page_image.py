"""Render PDF pages to numpy images using PyMuPDF."""

import numpy as np


def pdf_to_images(filepath: str, dpi: int = 300):
    """Convert each PDF page to a (numpy RGB array, width_pts, height_pts) tuple.

    Args:
        filepath: Path to PDF file.
        dpi: Rendering DPI.

    Yields:
        (img_array, page_width_pts, page_height_pts) per page.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(filepath)
    for page in doc:
        rect = page.rect
        pix = page.get_pixmap(dpi=dpi)
        # pix.samples is RGBA; drop alpha channel
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1)
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]  # RGBA → RGB
        elif arr.shape[2] == 1:
            arr = np.stack([arr.squeeze()] * 3, axis=-1)  # grayscale → RGB
        yield arr, rect.width, rect.height
    doc.close()
