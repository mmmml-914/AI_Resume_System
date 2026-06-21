"""RAG 知识库检索模块 — 将 Kaggle 简历向量化，评分时检索同类样本作为参考"""
import os
import json
import hashlib
import pandas as pd
from typing import Optional

# 使用 HuggingFace 国内镜像（Windows 下网络受限）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_EMBEDDING_MODEL = None  # 模块级缓存，避免重复加载
_CHROMA_CLIENT = None   # 模块级缓存 ChromaDB 客户端

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
KAGGLE_CSV = os.path.join(DATA_DIR, "UpdatedResumeDataSet.csv")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")


def get_embedding_model():
    """懒加载 embedding 模型（模块级缓存）"""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from sentence_transformers import SentenceTransformer
        print("[RAG] 加载 embedding 模型...")
        _EMBEDDING_MODEL = SentenceTransformer('BAAI/bge-small-zh-v1.5')
    return _EMBEDDING_MODEL


def get_chroma_collection():
    """获取 ChromaDB 集合（懒加载，client 模块级缓存）"""
    global _CHROMA_CLIENT
    import chromadb
    if _CHROMA_CLIENT is None:
        _CHROMA_CLIENT = chromadb.PersistentClient(path=CHROMA_DIR)
    return _CHROMA_CLIENT.get_or_create_collection(
        name="resumes",
        metadata={"hnsw:space": "cosine"},
    )


def build_vector_store():
    """将 Kaggle 和优秀简历库向量化存入 ChromaDB"""
    if not os.path.exists(KAGGLE_CSV):
        return {"error": "Kaggle CSV not found"}

    df = pd.read_csv(KAGGLE_CSV)
    df["Category"] = df["Category"].str.strip()

    model = get_embedding_model()
    collection = get_chroma_collection()

    # Check existing count
    existing = collection.count()
    if existing >= len(df):
        print(f"[RAG] 向量库已存在 ({existing} 条)，跳过构建")
        return {"status": "skipped", "count": existing}

    # 清空重建
    try:
        collection.delete(where={})
    except Exception:
        pass

    batch_size = 50
    all_ids, all_embeddings, all_metadatas, all_documents = [], [], [], []

    for idx, row in df.iterrows():
        resume_text = row["Resume"]
        category = row["Category"]
        doc_id = f"kaggle_{idx}"

        all_ids.append(doc_id)
        all_metadatas.append({"category": category, "source": "kaggle"})
        all_documents.append(resume_text[:5000])  # 截断节省空间

        # 分批编码和插入
        if len(all_ids) >= batch_size or idx == len(df) - 1:
            print(f"  编码 {len(all_ids)} 条...")
            embeddings = model.encode(all_documents, show_progress_bar=False).tolist()
            collection.add(
                ids=all_ids,
                embeddings=embeddings,
                metadatas=all_metadatas,
                documents=all_documents,
            )
            all_ids, all_embeddings, all_metadatas, all_documents = [], [], [], []

    total = collection.count()
    print(f"[RAG] 向量库构建完成，共 {total} 条")
    return {"status": "built", "count": total}


def retrieve_similar(resume_text: str, category: Optional[str] = None, top_k: int = 5) -> list:
    """检索与输入简历最相似的同类简历

    返回格式:
    [
        {"category": "Java Developer", "content": "...", "distance": 0.15},
        ...
    ]
    """
    collection = get_chroma_collection()
    model = get_embedding_model()

    if collection.count() == 0:
        return []

    query_vec = model.encode([resume_text[:5000]]).tolist()

    # 按类别过滤（如果有）
    where = {"category": category} if category else None

    results = collection.query(
        query_embeddings=query_vec,
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    retrieved = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            retrieved.append({
                "category": results["metadatas"][0][i]["category"],
                "content": results["documents"][0][i][:2000],
                "distance": round(results["distances"][0][i], 4),
            })

    return retrieved


def build_context_prompt(resume_text: str, category: Optional[str] = None) -> str:
    """构建 RAG 上下文，注入到评分 prompt 中"""
    similar = retrieve_similar(resume_text, category, top_k=3)

    if not similar:
        return ""

    parts = ["\n## 参考样本（同类简历）"]
    for i, s in enumerate(similar, 1):
        parts.append(f"\n--- 参考样本 {i}（{s['category']}，相似度:{s['distance']}）---")
        parts.append(s["content"])

    return "\n".join(parts)


if __name__ == "__main__":
    build_vector_store()

    # 测试
    test = "I am a Java developer with 5 years of experience in Spring Boot and microservices."
    ctx = build_context_prompt(test, "Java Developer")
    print("=== RAG 检索测试 ===")
    print(ctx[:1000])
