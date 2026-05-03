"""Cross-Encoder 리랭커 — sentence-transformers 기반 (lazy import)."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from src.retrieval import SearchResult

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_reranker: Any = None
_reranker_model_name: str | None = None
_reranker_lock = threading.Lock()


def load_reranker(model_name: str = RERANKER_MODEL) -> CrossEncoder:
    """Cross-Encoder 모델 로드 (lazy singleton, thread-safe)."""
    global _reranker, _reranker_model_name  # noqa: PLW0603
    with _reranker_lock:
        if _reranker is None or _reranker_model_name != model_name:
            from sentence_transformers import CrossEncoder

            logger.info("Cross-Encoder 로드: %s", model_name)
            _reranker = CrossEncoder(model_name)
            _reranker_model_name = model_name
        return _reranker


def rerank(
    query: str,
    results: list[SearchResult],
    top_k: int = 5,
    model_name: str = RERANKER_MODEL,
) -> list[SearchResult]:
    """검색 결과를 Cross-Encoder로 리랭킹."""
    if not results:
        return []

    model = load_reranker(model_name)
    pairs = [(query, r.content) for r in results]
    scores = model.predict(pairs)

    scored = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)

    return [
        SearchResult(
            content=result.content,
            score=float(score),
            metadata=result.metadata,
            rank=rank,
        )
        for rank, (score, result) in enumerate(scored[:top_k])
    ]
