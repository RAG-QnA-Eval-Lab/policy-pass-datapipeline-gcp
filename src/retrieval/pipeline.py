"""검색 파이프라인 오케스트레이션 — 4가지 전략 통합.

사용법:
    python -m src.retrieval.pipeline --query "청년 주거 지원 정책" --strategy hybrid_rerank
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

import faiss

from config.settings import settings
from src.ingestion.embedder import embed_texts
from src.retrieval import SearchResult
from src.retrieval.bm25_store import build_bm25_index, search_bm25
from src.retrieval.hybrid import hybrid_search
from src.retrieval.reranker import rerank
from src.retrieval.vector_store import search as vector_search

logger = logging.getLogger(__name__)


class SearchStrategy(str, Enum):
    VECTOR_ONLY = "vector_only"
    BM25_ONLY = "bm25_only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class RetrievalPipeline:
    """검색 파이프라인 — FAISS + BM25 + RRF + Cross-Encoder."""

    def __init__(
        self,
        index_dir: str | Path | None = None,
        top_k: int | None = None,
        rerank_top_k: int | None = None,
    ):
        index_dir = Path(index_dir or "data/index")
        self.top_k = top_k if top_k is not None else settings.top_k
        self.rerank_top_k = rerank_top_k if rerank_top_k is not None else settings.rerank_top_k

        index_path = index_dir / "faiss.index"
        metadata_path = index_dir / "metadata.json"

        if not index_path.exists():
            raise FileNotFoundError(f"FAISS 인덱스 없음: {index_path}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"메타데이터 없음: {metadata_path}")

        self.index = faiss.read_index(str(index_path))
        with open(metadata_path, encoding="utf-8") as f:
            self.metadata: list[dict] = json.load(f)

        self.bm25, self._bm25_docs = build_bm25_index(self.metadata)

        logger.info(
            "RetrievalPipeline 초기화: %d vectors, dim=%d",
            self.index.ntotal,
            self.index.d,
        )

    def search(
        self,
        query: str,
        strategy: SearchStrategy | str = SearchStrategy.HYBRID,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """쿼리 검색 — 전략별 분기."""
        strategy = SearchStrategy(strategy)
        top_k = top_k if top_k is not None else self.top_k

        if strategy == SearchStrategy.BM25_ONLY:
            return search_bm25(query, self.bm25, self._bm25_docs, top_k=top_k)

        query_embedding = embed_texts([query])[0]
        if len(query_embedding) != self.index.d:
            raise ValueError(
                f"임베딩 차원 불일치: query_dim={len(query_embedding)}, "
                f"index_dim={self.index.d}, embedding_model={settings.embedding_model}"
            )

        if strategy == SearchStrategy.VECTOR_ONLY:
            return vector_search(query_embedding, self.index, self.metadata, top_k=top_k)

        vector_results = vector_search(query_embedding, self.index, self.metadata, top_k=top_k)
        bm25_results = search_bm25(query, self.bm25, self._bm25_docs, top_k=top_k)
        hybrid_results = hybrid_search(vector_results, bm25_results)

        if strategy == SearchStrategy.HYBRID:
            return hybrid_results[:top_k]

        try:
            return rerank(query, hybrid_results, top_k=self.rerank_top_k)
        except Exception:
            logger.warning("Cross-Encoder rerank failed — falling back to hybrid results")
            return hybrid_results[:top_k]


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path as _Path

    from dotenv import load_dotenv

    load_dotenv(_Path(__file__).parent.parent.parent / ".env")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="검색 파이프라인 테스트")
    parser.add_argument("--query", required=True, help="검색 쿼리")
    parser.add_argument("--index-dir", default="data/index", help="인덱스 디렉토리")
    parser.add_argument(
        "--strategy",
        default="hybrid_rerank",
        choices=[s.value for s in SearchStrategy],
    )
    parser.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args()

    pipeline = RetrievalPipeline(index_dir=args.index_dir, top_k=args.top_k)
    results = pipeline.search(args.query, strategy=args.strategy)

    print(f"\n검색 결과 ({args.strategy}): {len(results)}건\n")
    for r in results:
        title = r.metadata.get("title", "제목 없음")
        print(f"  [{r.rank}] {title} (score={r.score:.4f})")
        print(f"      {r.content[:100]}...")
        print()

    output = [
        {"rank": r.rank, "score": r.score, "title": r.metadata.get("title", ""), "content": r.content[:200]}
        for r in results
    ]
    print(json.dumps(output, ensure_ascii=False, indent=2))
