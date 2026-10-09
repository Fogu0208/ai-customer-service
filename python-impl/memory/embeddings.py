"""
文本向量化 — 调用 OpenAI 兼容的 /embeddings 接口
默认使用 BAAI/bge-m3（硅基流动等平台均提供），输出归一化向量，配合 FAISS 内积索引即为余弦相似度。
"""

from __future__ import annotations

import os

import numpy as np
from openai import OpenAI


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"


class EmbeddingClient:
    """OpenAI 兼容接口的文本向量化客户端"""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        batch_size: int = 16,
    ):
        self.model = model or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self.batch_size = batch_size
        self._client = OpenAI(
            api_key=api_key or os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
            timeout=30,
            max_retries=2,
        )

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).astype(np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """批量向量化，返回 shape=(len(texts), dim) 的归一化矩阵"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            response = self._client.embeddings.create(model=self.model, input=batch)
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return self._normalize(np.asarray(vectors, dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]
