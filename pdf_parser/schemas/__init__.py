"""Pydantic schemas for the PDF parser API responses."""

from __future__ import annotations
from pydantic import BaseModel
from typing import Literal, Optional


class Block(BaseModel):
    """单个内容块：文本、标题、表格或图表。"""
    type: Literal["text", "heading", "table", "figure"]
    bbox: list[float]  # [x1, y1, x2, y2] in PDF points
    content: str = ""
    confidence: float = 0.0
    # 表格专用
    rows: Optional[int] = None
    cols: Optional[int] = None
    # 图表专用（Phase 2）
    figure_file: Optional[str] = None
    alt_text: Optional[str] = None


class Page(BaseModel):
    """单页解析结果。"""
    page_num: int
    width: float
    height: float
    blocks: list[Block]


class ParseResult(BaseModel):
    """完整的 PDF 解析结果。"""
    filename: str
    total_pages: int
    pages: list[Page]
