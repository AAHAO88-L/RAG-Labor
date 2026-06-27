"""语义分块器单元测试。"""

import pytest
from utils.semantic_chunker import chunk_text_semantic, _cn_number, _detect_structure


SAMPLE_LAW = """中华人民共和国劳动法

第一章 总则

第一条 为了保护劳动者的合法权益，调整劳动关系，建立和维护适应社会主义市场经济的劳动制度，促进经济发展和社会进步，根据宪法，制定本法。

第二条 在中华人民共和国境内的企业、个体经济组织和与之形成劳动关系的劳动者，适用本法。国家机关、事业组织、社会团体和与之建立劳动合同关系的劳动者，依照本法执行。

第二章 促进就业

第十条 国家通过促进经济和社会发展，创造就业条件，扩大就业机会。
"""


def test_cn_number_single():
    assert _cn_number("一") == 1
    assert _cn_number("二") == 2
    assert _cn_number("十") == 10


def test_cn_number_compound():
    assert _cn_number("十二") == 12
    assert _cn_number("二十") == 20
    assert _cn_number("二十五") == 25


def test_cn_number_hundreds():
    assert _cn_number("一百") == 100
    assert _cn_number("三百零二") == 302
    assert _cn_number("一百一十") == 110


def test_cn_number_thousands():
    assert _cn_number("一千") == 1000
    assert _cn_number("一千零一") == 1001
    assert _cn_number("二千零二十") == 2020


def test_detect_structure_has_chapters():
    segs = _detect_structure(SAMPLE_LAW)
    assert len(segs) > 0


def test_detect_structure_preamble():
    """第一章前面的内容应该被识别为前言。"""
    segs = _detect_structure(SAMPLE_LAW)
    # 前言"中华人民共和国劳动法"
    contents = [s["body"] for s in segs]
    assert any("中华人民共和国劳动法" in c for c in contents)


def test_chunk_text_semantic_returns_list():
    chunks = chunk_text_semantic(SAMPLE_LAW, chunk_size=800)
    assert len(chunks) > 0
    for text, meta in chunks:
        assert isinstance(text, str)
        assert len(text) > 0


def test_chunk_metadata_has_source_fields():
    chunks = chunk_text_semantic(SAMPLE_LAW, chunk_size=200)
    chapters = [m.get("chapter") for _, m in chunks if m.get("chapter")]
    assert any("第一章" in c for c in chapters)
    assert any("第二章" in c for c in chapters)


def test_chunk_metadata_has_article():
    chunks = chunk_text_semantic(SAMPLE_LAW, chunk_size=200)
    articles = [m.get("article") for _, m in chunks if m.get("article")]
    assert any("第一条" in a for a in articles)


def test_long_chunk_split():
    """超过 chunk_size 的条文应被拆分。"""
    long_text = "中华人民共和国劳动法\n\n" + "第一条 " + "A" * 1000 + "。\n\n"
    chunks = chunk_text_semantic(long_text, chunk_size=200)
    assert len(chunks) >= 2


def test_article_inheritance():
    """无 article 的片段应继承前一个片段的 article。"""
    text = "第一条 内容。\n\n一些补充说明。\n\n第二条 更多内容。"
    chunks = chunk_text_semantic(text, chunk_size=500)
    # "一些补充说明"应该继承"第一条"
    articles = [m.get("article") for _, m in chunks]
    assert "第一条" in articles


def test_empty_text():
    chunks = chunk_text_semantic("", chunk_size=800)
    assert len(chunks) == 0
