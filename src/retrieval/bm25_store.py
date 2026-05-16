"""BM25 키워드 검색 — rank-bm25 기반."""

from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Okapi

from src.retrieval import SearchResult

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")


def tokenize_korean(text: str) -> list[str]:
    """한국어 공백 기반 토크나이저."""
    cleaned = text.strip()
    return _WHITESPACE_RE.split(cleaned) if cleaned else []


def build_bm25_index(documents: list[dict]) -> tuple[BM25Okapi, list[dict]]:
    """문서 리스트 → BM25 인덱스 빌드.

    Args:
        documents: content 키를 포함하는 dict 리스트 (metadata.pkl 형식).

    Returns:
        (BM25 인덱스, 원본 documents 리스트).
    """
    corpus = [tokenize_korean(doc.get("content", "")) for doc in documents]
    bm25 = BM25Okapi(corpus)
    logger.info("BM25 인덱스 빌드: %d문서", len(documents))
    return bm25, documents


def search_bm25(
    query: str,
    bm25: BM25Okapi,
    documents: list[dict],
    top_k: int = 10,
) -> list[SearchResult]:
    """BM25 키워드 검색."""
    tokenized_query = tokenize_korean(query)
    scores = bm25.get_scores(tokenized_query)

    top_indices = scores.argsort()[::-1][:top_k]

    results: list[SearchResult] = []
    for idx in top_indices:
        if scores[idx] <= 0:
            continue
        doc = documents[idx]
        content = doc.get("content", "")
        meta = {k: v for k, v in doc.items() if k != "content"}
        results.append(SearchResult(content=content, score=float(scores[idx]), metadata=meta, rank=len(results)))

    return results
