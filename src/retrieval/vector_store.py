"""FAISS 벡터 검색 — stateless 함수."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import faiss
import numpy as np

from src.retrieval import SearchResult

logger = logging.getLogger(__name__)


def load_index(
    index_path: str | Path,
    metadata_path: str | Path,
) -> tuple[faiss.IndexFlatL2, list[dict]]:
    """FAISS 인덱스 + 메타데이터 로드."""
    index_path = Path(index_path)
    metadata_path = Path(metadata_path)

    if not index_path.exists():
        raise FileNotFoundError(f"FAISS 인덱스 없음: {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"메타데이터 없음: {metadata_path}")

    index = faiss.read_index(str(index_path))
    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)

    logger.info("인덱스 로드: %d vectors, dim=%d", index.ntotal, index.d)
    return index, metadata


def search(
    query_embedding: list[float],
    index: faiss.IndexFlatL2,
    metadata: list[dict],
    top_k: int = 10,
) -> list[SearchResult]:
    """쿼리 임베딩으로 FAISS 검색."""
    query_vec = np.array([query_embedding], dtype=np.float32)
    distances, indices = index.search(query_vec, min(top_k, index.ntotal))

    results: list[SearchResult] = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx == -1:
            continue
        meta = metadata[idx]
        content = meta.get("content", "")
        filtered_meta = {k: v for k, v in meta.items() if k != "content"}
        results.append(
            SearchResult(
                content=content,
                score=float(dist),
                metadata=filtered_meta,
                rank=len(results),
            )
        )

    return results
