"""知识库索引构建 — 写入 ChromaDB"""

import os
import uuid
import chromadb
from models.embeddings import embed_texts
from utils.file_loader import load_files_from_folder, load_file_structured
from utils.semantic_chunker import chunk_text_semantic
from retrieval.hybrid import build_bm25_index

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP_RATIO = float(os.getenv("CHUNK_OVERLAP", "0.1"))
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
STRUCTURED_PARSE = os.getenv("STRUCTURED_PDF_PARSE", "0") == "1"


def _structured_to_flat_text(parsed):
    """将结构化 JSON 转为可进入 semantic_chunker 的纯文本字符串。"""
    parts = []
    for page in parsed.get("pages", []):
        for block in page.get("blocks", []):
            t = block.get("type")
            content = block.get("content", "")
            if t in ("text", "heading"):
                parts.append(content)
            elif t == "table" and content:
                parts.append(content)
            elif t == "figure" and block.get("alt_text"):
                parts.append(f"【图注：{block['alt_text']}】")
    return "\n".join(parts)


def build_index(data_folder="data"):
    docs = load_files_from_folder(data_folder)
    all_texts = []
    all_metadatas = []
    for path, text in docs.items():
        rel_path = os.path.relpath(path, os.path.dirname(os.path.abspath(__file__)))

        # 结构化 PDF 解析（启用时）
        if STRUCTURED_PARSE and path.lower().endswith(".pdf"):
            try:
                parsed = load_file_structured(path)
                text = _structured_to_flat_text(parsed)
            except Exception as e:
                print(f"  [WARN] 结构化解析失败 ({path}), 回退到纯文本: {e}")

        for i, (chunk, sem_meta) in enumerate(chunk_text_semantic(
            text, chunk_size=CHUNK_SIZE, overlap_ratio=CHUNK_OVERLAP_RATIO
        )):
            all_texts.append(chunk)
            meta = {"source": rel_path, "chunk_id": i}
            if sem_meta.get("article"):
                meta["article"] = sem_meta["article"]
            if sem_meta.get("chapter"):
                meta["chapter"] = sem_meta["chapter"]
            if sem_meta.get("section"):
                meta["section"] = sem_meta["section"]
            all_metadatas.append(meta)

    if not all_texts:
        print("未找到任何支持的文件，请将知识文件放入 data/ 目录。")
        return

    print(f"生成 {len(all_texts)} 个片段的 embedding...")
    embeddings = embed_texts(all_texts)

    print(f"写入 ChromaDB ({CHROMA_PATH})...")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # 删除旧集合重建
    try:
        client.delete_collection("labor_laws")
    except Exception:
        pass

    collection = client.create_collection(
        name="labor_laws",
        metadata={"hnsw:space": "l2"},
    )

    ids = [uuid.uuid4().hex[:16] for _ in range(len(all_texts))]
    emb_list = [e.tolist() for e in embeddings]

    # 分批写入，每批 100
    batch_size = 100
    for i in range(0, len(all_texts), batch_size):
        end = min(i + batch_size, len(all_texts))
        collection.add(
            ids=ids[i:end],
            embeddings=emb_list[i:end],
            documents=all_texts[i:end],
            metadatas=all_metadatas[i:end],
        )
        print(f"  已写入 {end}/{len(all_texts)}")

    print(f"构建完成！ChromaDB 索引保存在 {CHROMA_PATH}")

    # 构建 BM25 索引
    build_bm25_index(all_texts, all_metadatas)


def add_document(filepath, cleanup=True, source_override=None):
    """增量添加单个文件到现有 ChromaDB 集合，并重建 BM25 索引。

    Args:
        filepath: 文件路径
        cleanup: 是否删除同名旧 chunks
        source_override: 覆盖 metadata 中的 source 字段（用于上传时的原始文件名）
    """
    from utils.file_loader import load_file, load_file_structured

    if STRUCTURED_PARSE and filepath.lower().endswith(".pdf"):
        try:
            parsed = load_file_structured(filepath)
            text = _structured_to_flat_text(parsed)
        except Exception as e:
            print(f"  [WARN] 结构化解析失败, 回退到纯文本: {e}")
            text = load_file(filepath)
    else:
        text = load_file(filepath)
    if not text.strip():
        raise ValueError("文件内容为空")

    rel_path = source_override or os.path.relpath(filepath, os.path.dirname(os.path.abspath(__file__)))
    sem_chunks = chunk_text_semantic(text, chunk_size=CHUNK_SIZE, overlap_ratio=CHUNK_OVERLAP_RATIO)
    chunks = []
    metadatas = []
    for i, (chunk_text, sem_meta) in enumerate(sem_chunks):
        if not chunk_text.strip():
            continue
        chunks.append(chunk_text)
        meta = {"source": rel_path, "chunk_id": i}
        if sem_meta.get("article"):
            meta["article"] = sem_meta["article"]
        if sem_meta.get("chapter"):
            meta["chapter"] = sem_meta["chapter"]
        if sem_meta.get("section"):
            meta["section"] = sem_meta["section"]
        metadatas.append(meta)

    if not chunks:
        raise ValueError("文件未能生成有效片段")

    print(f"  文件 {os.path.basename(filepath)} 切分为 {len(chunks)} 个片段")

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection("labor_laws")
    except Exception:
        raise RuntimeError("ChromaDB 集合不存在，请先运行 ingest.py 构建索引。")

    # 如果 cleanup，先删除该文件的旧 chunks
    if cleanup:
        try:
            existing = collection.get(where={"source": rel_path})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                print(f"  已删除 {len(existing['ids'])} 个旧片段")
        except Exception:
            pass

    embeddings = embed_texts(chunks)
    ids = [uuid.uuid4().hex[:16] for _ in range(len(chunks))]

    collection.add(
        ids=ids,
        embeddings=[e.tolist() for e in embeddings],
        documents=chunks,
        metadatas=metadatas,
    )

    print(f"  索引更新完成，新增 {len(chunks)} 个片段")

    # 增量更新 BM25 索引（不再全量 scan ChromaDB）
    try:
        from retrieval.hybrid import add_to_bm25_index
        add_to_bm25_index(chunks, metadatas)
    except Exception as e:
        print(f"  [WARN] BM25 增量更新失败：{e}")

    return len(chunks)


def add_documents(filepaths, source_names=None):
    """批量添加多个文件。"""
    total_chunks = 0
    for i, fp in enumerate(filepaths):
        src = source_names[i] if source_names and i < len(source_names) else None
        try:
            n = add_document(fp, cleanup=True, source_override=src)
            total_chunks += n
            print(f"  [OK] {os.path.basename(fp) if not src else src}: {n} 片段")
        except Exception as e:
            print(f"  [ERR] {os.path.basename(fp)}: {e}")
    print(f"  批量处理完成，共 {total_chunks} 个片段")
    return total_chunks


def remove_document(source_path):
    """根据 source 路径从 ChromaDB 中删除文档，同时更新 BM25 索引。

    Args:
        source_path: metadata 中的 source 字段值（如 "data/laws/xxx.txt"）
    """
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        collection = client.get_collection("labor_laws")
    except Exception:
        raise RuntimeError("ChromaDB 集合不存在。")

    existing = collection.get(where={"source": source_path})
    if not existing["ids"]:
        print(f"  未找到 source={source_path} 的文档")
        return 0

    count = len(existing["ids"])
    collection.delete(ids=existing["ids"])
    print(f"  已从 ChromaDB 删除 {count} 个片段")

    # 增量更新 BM25 索引（移除对应条目，避免全量扫描 ChromaDB）
    try:
        from retrieval.hybrid import remove_from_bm25_index
        removed_bm25 = remove_from_bm25_index(source_path)
        print(f"  BM25 索引已更新，移除 {removed_bm25} 条")
    except Exception as e:
        print(f"  [WARN] BM25 增量更新失败：{e}")

    return count


if __name__ == "__main__":
    build_index()
