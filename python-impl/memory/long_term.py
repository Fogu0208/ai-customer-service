"""
长期记忆 — 基于向量数据库的持久化记忆
存储用户画像、历史工单、知识库文档等需要持久化的信息。
支持语义相似度检索，用于RAG知识检索Agent。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from memory.embeddings import EmbeddingClient

try:
    import faiss
except ImportError:
    faiss = None


logger = logging.getLogger(__name__)


class LongTermMemory:
    """
    长期记忆：基于FAISS的向量检索。

    特点：
    - 调用 Embedding 模型向量化，FAISS 内积索引（向量已归一化，等价于余弦相似度）
    - 持久化到磁盘，跨会话保持；按内容哈希去重，重启不会重复写入
    - 索引记录所用 Embedding 模型，换模型后自动重建
    - Embedding 不可用时降级为中文二元组关键词检索
    - 生产环境可切换为Milvus/Pinecone

    文档分块策略：
    - 固定长度分块 (512 字符) + 重叠窗口 (128 字符)
    - 按段落自然分割优先
    """

    def __init__(
        self,
        index_path: str = "./vector_store/faiss_index",
        embedder: EmbeddingClient | None = None,
    ):
        self.index_path = Path(index_path)
        self.metadata_path = self.index_path.with_suffix(".meta.json")
        self.embedder = embedder if embedder is not None else self._default_embedder()
        self._documents: list[dict[str, Any]] = []
        self._doc_ids: set[str] = set()
        self._index = None
        self._matrix: np.ndarray | None = None
        self._load()

    @staticmethod
    def _default_embedder() -> EmbeddingClient | None:
        try:
            return EmbeddingClient()
        except Exception as e:
            logger.warning("Embedding 客户端初始化失败，长期记忆降级为关键词检索: %s", e)
            return None

    # ─── 向量存储 ───

    def _vector_count(self) -> int:
        if self._index is not None:
            return self._index.ntotal
        if self._matrix is not None:
            return self._matrix.shape[0]
        return 0

    def _vector_ready(self) -> bool:
        """每篇文档都有对应向量时才走向量检索，否则索引与文档对不齐"""
        return self.embedder is not None and self._vector_count() == len(self._documents)

    def _add_vectors(self, vectors: np.ndarray) -> None:
        if faiss is not None:
            if self._index is None:
                self._index = faiss.IndexFlatIP(vectors.shape[1])
            self._index.add(vectors)
        else:
            self._matrix = vectors if self._matrix is None else np.vstack([self._matrix, vectors])

    def _vector_search(self, query_vec: np.ndarray, top_k: int) -> list[dict]:
        k = min(top_k, len(self._documents))
        if self._index is not None:
            scores, indices = self._index.search(query_vec.reshape(1, -1), k)
            pairs = zip(scores[0], indices[0])
        else:
            sims = self._matrix @ query_vec
            pairs = ((sims[i], i) for i in np.argsort(-sims)[:k])

        results = []
        for score, idx in pairs:
            if idx < 0 or idx >= len(self._documents):
                continue
            doc = self._documents[idx].copy()
            doc["score"] = float(score)
            results.append(doc)
        return results

    # ─── 持久化 ───

    def _load(self) -> None:
        """从磁盘恢复文档；索引缺失或 Embedding 模型变化时重新向量化"""
        if not self.metadata_path.exists():
            return

        with open(self.metadata_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if isinstance(meta, list):
            documents, model = meta, None
        else:
            documents, model = meta.get("documents", []), meta.get("embedding_model")

        self._documents = documents
        self._doc_ids = {doc["id"] for doc in documents}

        if self.embedder is None or not documents:
            return

        if faiss is not None and model == self.embedder.model and self.index_path.exists():
            try:
                index = faiss.read_index(str(self.index_path))
                if index.ntotal == len(documents):
                    self._index = index
                    return
            except Exception as e:
                logger.warning("FAISS 索引读取失败，将重新向量化: %s", e)

        try:
            self._add_vectors(self.embedder.embed_documents([doc["content"] for doc in documents]))
        except Exception as e:
            logger.warning("文档重新向量化失败，长期记忆降级为关键词检索: %s", e)

    def save(self) -> None:
        """持久化索引到磁盘"""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        if faiss is not None and self._index is not None:
            faiss.write_index(self._index, str(self.index_path))

        meta = {
            "embedding_model": self.embedder.model if self.embedder else None,
            "documents": self._documents,
        }
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    # ─── 写入 ───

    def add_document(self, content: str, source: str = "", metadata: dict | None = None) -> str:
        """添加文档到向量库，返回文档 ID（内容已存在时直接返回已有 ID）"""
        self.add_documents_batch([{"content": content, "source": source, "metadata": metadata}])
        return self._doc_id(content.strip())

    def add_documents_batch(self, documents: list[dict]) -> list[str]:
        """批量添加文档，一次请求完成向量化；返回新增文档的 ID（重复内容会跳过）"""
        new_docs = []
        for doc in documents:
            content = (doc.get("content") or "").strip()
            if not content:
                continue
            doc_id = self._doc_id(content)
            if doc_id in self._doc_ids:
                continue
            self._doc_ids.add(doc_id)
            new_docs.append({
                "id": doc_id,
                "content": content,
                "source": doc.get("source", ""),
                "metadata": doc.get("metadata") or {},
            })

        if not new_docs:
            return []

        vectors = None
        if self._vector_ready():
            try:
                vectors = self.embedder.embed_documents([doc["content"] for doc in new_docs])
            except Exception as e:
                logger.warning("文档向量化失败，长期记忆降级为关键词检索: %s", e)

        self._documents.extend(new_docs)
        if vectors is not None:
            self._add_vectors(vectors)

        return [doc["id"] for doc in new_docs]

    def load_knowledge_base(self, kb_dir: str | Path) -> int:
        """从目录批量加载知识库文档（.txt / .md），返回新增片段数"""
        kb_path = Path(kb_dir)
        if not kb_path.exists():
            return 0

        documents = []
        for file_path in sorted(kb_path.glob("**/*")):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            content = file_path.read_text(encoding="utf-8")
            for chunk in self._chunk_text(content):
                documents.append({
                    "content": chunk,
                    "source": file_path.name,
                    "metadata": {"file": str(file_path)},
                })

        return len(self.add_documents_batch(documents))

    # ─── 检索 ───

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """语义相似度检索"""
        if not self._documents:
            return []

        if self._vector_ready():
            try:
                return self._vector_search(self.embedder.embed_query(query), top_k)
            except Exception as e:
                logger.warning("向量检索失败，降级为关键词检索: %s", e)

        return self.keyword_search(query, top_k)

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        text = re.sub(r"[\W_]+", "", text.lower())
        return {text[i:i + 2] for i in range(len(text) - 1)} or {text}

    def keyword_search(self, query: str, top_k: int = 5) -> list[dict]:
        """中文二元组重叠度检索，用作降级方案和评测基线"""
        query_grams = self._bigrams(query)
        scored = []
        for doc in self._documents:
            overlap = len(query_grams & self._bigrams(doc["content"]))
            if overlap > 0:
                scored.append((overlap / len(query_grams), doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**doc, "score": score} for score, doc in scored[:top_k]]

    @property
    def size(self) -> int:
        return len(self._documents)

    @staticmethod
    def _doc_id(content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()[:12]

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
        """
        文本分块：固定长度 + 重叠窗口。
        优先按段落分割，段落过长则按句子分割。
        """
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
                    current_chunk = overlap_text + para + "\n\n"
                else:
                    sentences = para.replace("。", "。\n").replace(".", ".\n").split("\n")
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if not sentence:
                            continue
                        if len(current_chunk) + len(sentence) <= chunk_size:
                            current_chunk += sentence
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks if chunks else [text[:chunk_size]]
