"""语义分块器 — 按法律文本结构（章/节/条）分块"""

import re

# 中文数字映射
_CN_NUM = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
}

_SENTENCE_END = re.compile(r'[。！？；\n]')
_CHAPTER_RE = re.compile(r'(第[一二三四五六七八九十百零]+章)')
_SECTION_RE = re.compile(r'(第[一二三四五六七八九十百零]+节)')
_ARTICLE_RE = re.compile(r'(第[一二三四五六七八九十百零]+条)')


def _cn_number(s):
    """将中文数字字符串转为 int，支持到千位（如'三百零二'→302）。"""
    total = 0
    curr = 0
    for ch in s:
        if ch in _CN_NUM:
            curr = _CN_NUM[ch]
        elif ch == '十':
            curr = curr * 10 if curr else 10
            total += curr
            curr = 0
        elif ch == '百':
            curr = curr * 100 if curr else 100
            total += curr
            curr = 0
        elif ch == '千':
            curr = curr * 1000 if curr else 1000
            total += curr
            curr = 0
        elif ch == '零':
            curr = 0
    total += curr
    return total


def _detect_structure(text):
    """解析法律文本结构，返回 list of dict:
    {type, heading, body, chapter, section, article}
    """
    segments = []

    # 按章节切分
    chapter_spans = list(_CHAPTER_RE.finditer(text))
    if chapter_spans:
        chapter_boundaries = [m.start() for m in chapter_spans]
        chapter_boundaries.append(len(text))
        for i in range(len(chapter_spans)):
            start = chapter_spans[i].start()
            end = chapter_boundaries[i + 1]
            chapter_title = chapter_spans[i].group(1)
            chapter_body = text[start + len(chapter_title):end].strip()
            _extract_articles(segments, chapter_body, chapter=chapter_title)

        # 第一章前面的文本（总则等）
        preamble = text[:chapter_spans[0].start()].strip()
        if preamble:
            _extract_articles(segments, preamble)
    else:
        # 没有章节，检测节级
        section_spans = list(_SECTION_RE.finditer(text))
        if section_spans:
            section_boundaries = [m.start() for m in section_spans]
            section_boundaries.append(len(text))
            for i in range(len(section_spans)):
                start = section_spans[i].start()
                end = section_boundaries[i + 1]
                section_title = section_spans[i].group(1)
                section_body = text[start + len(section_title):end].strip()
                _extract_articles(segments, section_body, section=section_title)
            preamble = text[:section_spans[0].start()].strip()
            if preamble:
                _extract_articles(segments, preamble)
        else:
            # 无结构化，直接按条切
            _extract_articles(segments, text)

    return segments


def _extract_articles(segments, body, chapter=None, section=None):
    """从一段文本中提取"条"级结构。"""
    article_spans = list(_ARTICLE_RE.finditer(body))
    if not article_spans:
        segments.append({
            'type': 'text',
            'heading': '',
            'body': body.strip(),
            'chapter': chapter,
            'section': section,
            'article': None,
        })
        return

    boundaries = [m.start() for m in article_spans]
    boundaries.append(len(body))
    for i in range(len(article_spans)):
        start = article_spans[i].start()
        end = boundaries[i + 1]
        article_title = article_spans[i].group(1)
        # 扣除"第X条"本身
        article_body = body[start:end].strip()
        segments.append({
            'type': 'article',
            'heading': article_title,
            'body': article_body,
            'chapter': chapter,
            'section': section,
            'article': article_title,
        })
    # 第一条之前的前言文本
    first_start = body[:article_spans[0].start()].strip()
    if first_start:
        segments.append({
            'type': 'text',
            'heading': '',
            'body': first_start,
            'chapter': chapter,
            'section': section,
            'article': None,
        })


def _split_long_body(body, chunk_size, overlap_ratio):
    """对超过 chunk_size 的段落按句子边界拆分，添加重叠。"""
    if len(body) <= chunk_size:
        return [body]

    sentences = _SENTENCE_END.split(body)
    # 恢复标点
    puncts = [m.group() for m in _SENTENCE_END.finditer(body)]

    pieces = []
    buf = ''
    for i, sent in enumerate(sentences):
        if not sent:
            continue
        punct = puncts[min(i, len(puncts) - 1)] if i < len(puncts) else ''
        if len(buf) + len(sent) + 1 <= chunk_size:
            buf += sent + punct
        else:
            if buf.strip():
                pieces.append(buf.strip())
            buf = sent + punct

        # 如果这一句本身就超过 chunk_size，强行截断
        if len(buf) > chunk_size and buf.strip():
            # 以 chunk_size 为界拆分，保留句子完整性尝试
            while len(buf) > chunk_size:
                cut = buf[:chunk_size]
                pieces.append(cut.strip())
                buf = buf[chunk_size:]

    if buf.strip():
        pieces.append(buf.strip())

    if len(pieces) <= 1:
        return pieces

    # 添加重叠
    overlap_len = int(chunk_size * overlap_ratio)
    result = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        # 从上一个 chunk 尾部取 overlap_len 字符做重叠前缀
        overlap = prev[-overlap_len:] if len(prev) > overlap_len else prev
        result.append(overlap + pieces[i])

    return result


def chunk_text_semantic(text, chunk_size=800, overlap_ratio=0.1):
    """对法律文本按语义结构分块。

    返回 list[tuple[str, dict]]:
      - str: 块文本
      - dict: {source, chunk_id, article, chapter, section}
    """
    segments = _detect_structure(text)

    # 先合并小片段
    merged = []
    buf_segments = []

    def _flush():
        nonlocal buf_segments
        if not buf_segments:
            return
        combined_text = ' '.join(s['body'] for s in buf_segments)
        combined_text = re.sub(r'\s+', '', combined_text)
        meta = {
            'article': buf_segments[0].get('article'),
            'chapter': buf_segments[0].get('chapter'),
            'section': buf_segments[0].get('section'),
        }
        merged.append((combined_text, meta))
        buf_segments = []

    for seg in segments:
        body = seg['body']
        if not body.strip():
            continue
        if len(body) <= chunk_size * 0.3 and not _ARTICLE_RE.search(body):
            # 小片段，暂存待合并
            buf_segments.append(seg)
        else:
            _flush()
            if len(body) <= chunk_size:
                meta = {
                    'article': seg.get('article'),
                    'chapter': seg.get('chapter'),
                    'section': seg.get('section'),
                }
                merged.append((body, meta))
            else:
                # 长段落拆分
                for piece in _split_long_body(body, chunk_size, overlap_ratio):
                    meta = {
                        'article': seg.get('article'),
                        'chapter': seg.get('chapter'),
                        'section': seg.get('section'),
                    }
                    merged.append((piece, meta))
    _flush()

    # 对无 article 的片段，继承前一个有 article 的值
    last_article = None
    for i, (text, meta) in enumerate(merged):
        if meta.get('article'):
            last_article = meta['article']
        elif last_article:
            meta['article'] = last_article

    return merged
