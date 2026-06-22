"""知识库索引构建 — 写入 ChromaDB"""

import os
import uuid
import chromadb
from models.embeddings import embed_texts
from utils.text_loader import load_text_files

CHUNK_SIZE = 800
CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")


def chunk_text(text, size=CHUNK_SIZE):
    chunks = []
    for i in range(0, len(text), size):
        c = text[i:i+size].strip()
        if c:
            chunks.append(c)
    return chunks


def build_index(data_folder="data"):
    docs = load_text_files(data_folder)
    all_texts = []
    all_metadatas = []
    for path, text in docs.items():
        rel_path = os.path.relpath(path, os.path.dirname(os.path.abspath(__file__)))
        for i, chunk in enumerate(chunk_text(text)):
            all_texts.append(chunk)
            all_metadatas.append({"source": rel_path, "chunk_id": i})

    if not all_texts:
        print("未找到任何文本文件，请将知识文件放入 data/ 目录。")
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


if __name__ == "__main__":
    build_index()
