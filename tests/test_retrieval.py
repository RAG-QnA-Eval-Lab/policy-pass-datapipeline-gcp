"""검색 시스템 테스트 — vector, bm25, hybrid, reranker, pipeline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

from src.retrieval import SearchResult
from src.retrieval.bm25_store import build_bm25_index, search_bm25, tokenize_korean
from src.retrieval.hybrid import hybrid_search, reciprocal_rank_fusion
from src.retrieval.vector_store import load_index, search

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture()
def sample_metadata() -> list[dict]:
    return [
        {"content": "청년 월세 지원 정책입니다. 월 최대 20만원 지원.", "title": "월세지원", "category": "housing"},
        {
            "content": "국민취업지원제도는 취업 준비 청년을 위한 정책입니다.",
            "title": "국민취업지원",
            "category": "employment",
        },
        {"content": "청년 전세자금 대출 정책. 최대 1억원까지 저금리 대출.", "title": "전세대출", "category": "housing"},
        {"content": "대학생 학자금 대출 지원. 등록금 전액 대출 가능.", "title": "학자금대출", "category": "education"},
        {"content": "청년 창업 지원금. 최대 5천만원 사업비 지원.", "title": "창업지원", "category": "startup"},
    ]


@pytest.fixture()
def faiss_index_and_metadata(sample_metadata: list[dict]) -> tuple[faiss.IndexFlatL2, list[dict]]:
    dim = 8
    vectors = np.random.default_rng(42).standard_normal((len(sample_metadata), dim)).astype(np.float32)
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)
    return index, sample_metadata


@pytest.fixture()
def index_dir(faiss_index_and_metadata: tuple[faiss.IndexFlatL2, list[dict]]) -> Path:
    index, metadata = faiss_index_and_metadata
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        faiss.write_index(index, str(tmppath / "faiss.index"))
        with open(tmppath / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False)
        yield tmppath


# ──────────────────────────────────────────────
# Vector Store
# ──────────────────────────────────────────────


class TestVectorStore:
    def test_load_index(self, index_dir: Path) -> None:
        index, metadata = load_index(index_dir / "faiss.index", index_dir / "metadata.json")
        assert index.ntotal == 5
        assert len(metadata) == 5

    def test_load_index_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_index(tmp_path / "missing.index", tmp_path / "missing.pkl")

    def test_search_returns_results(self, faiss_index_and_metadata: tuple[faiss.IndexFlatL2, list[dict]]) -> None:
        index, metadata = faiss_index_and_metadata
        query_vec = np.random.default_rng(99).standard_normal(8).astype(np.float32).tolist()
        results = search(query_vec, index, metadata, top_k=3)
        assert len(results) == 3
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].rank == 0
        assert results[1].rank == 1

    def test_search_top_k_exceeds_total(self, faiss_index_and_metadata: tuple[faiss.IndexFlatL2, list[dict]]) -> None:
        index, metadata = faiss_index_and_metadata
        query_vec = np.random.default_rng(99).standard_normal(8).astype(np.float32).tolist()
        results = search(query_vec, index, metadata, top_k=100)
        assert len(results) == 5


# ──────────────────────────────────────────────
# BM25 Store
# ──────────────────────────────────────────────


class TestBM25Store:
    def test_tokenize_korean(self) -> None:
        tokens = tokenize_korean("청년 월세 지원 정책")
        assert tokens == ["청년", "월세", "지원", "정책"]

    def test_tokenize_empty(self) -> None:
        assert tokenize_korean("") == []

    def test_build_and_search(self, sample_metadata: list[dict]) -> None:
        bm25, docs = build_bm25_index(sample_metadata)
        results = search_bm25("청년 월세", bm25, docs, top_k=3)
        assert len(results) > 0
        assert results[0].content  # 내용이 비어 있지 않은지
        assert "월세" in results[0].content or "청년" in results[0].content

    def test_no_match_returns_empty(self, sample_metadata: list[dict]) -> None:
        bm25, docs = build_bm25_index(sample_metadata)
        results = search_bm25("xyznonexistent", bm25, docs, top_k=3)
        assert len(results) == 0


# ──────────────────────────────────────────────
# Hybrid (RRF)
# ──────────────────────────────────────────────


class TestHybrid:
    def test_rrf_combines_rankings(self) -> None:
        vector_results = [
            SearchResult(content="A", score=0.1, metadata={}, rank=0),
            SearchResult(content="B", score=0.2, metadata={}, rank=1),
            SearchResult(content="C", score=0.3, metadata={}, rank=2),
        ]
        bm25_results = [
            SearchResult(content="B", score=5.0, metadata={}, rank=0),
            SearchResult(content="D", score=3.0, metadata={}, rank=1),
            SearchResult(content="A", score=1.0, metadata={}, rank=2),
        ]
        fused = hybrid_search(vector_results, bm25_results)
        contents = [r.content for r in fused]
        assert "A" in contents
        assert "B" in contents
        # B는 양쪽 모두 상위 → RRF 점수가 가장 높아야 함
        assert fused[0].content == "B"

    def test_rrf_empty_input(self) -> None:
        result = reciprocal_rank_fusion([])
        assert result == []

    def test_rrf_single_list(self) -> None:
        results = [
            SearchResult(content="X", score=1.0, metadata={}, rank=0),
        ]
        fused = reciprocal_rank_fusion([results])
        assert len(fused) == 1
        assert fused[0].content == "X"


# ──────────────────────────────────────────────
# Reranker
# ──────────────────────────────────────────────


class TestReranker:
    @patch("src.retrieval.reranker.load_reranker")
    def test_rerank_reorders(self, mock_load: MagicMock) -> None:
        from src.retrieval.reranker import rerank

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.1, 0.9, 0.05])
        mock_load.return_value = mock_model

        results = [
            SearchResult(content="비관련 내용", score=0.5, metadata={}, rank=0),
            SearchResult(content="청년 주거 지원 월세 보조금 정책", score=0.3, metadata={}, rank=1),
            SearchResult(content="아무 관계없는 문서", score=0.1, metadata={}, rank=2),
        ]
        reranked = rerank("청년 월세 지원", results, top_k=2)
        assert len(reranked) == 2
        assert reranked[0].content == "청년 주거 지원 월세 보조금 정책"
        assert reranked[0].rank == 0
        assert reranked[1].rank == 1

    def test_rerank_empty(self) -> None:
        from src.retrieval.reranker import rerank

        assert rerank("query", [], top_k=5) == []


# ──────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────


class TestPipeline:
    def test_pipeline_init(self, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline

        pipeline = RetrievalPipeline(index_dir=index_dir)
        assert pipeline.index.ntotal == 5
        assert len(pipeline.metadata) == 5

    def test_pipeline_missing_index(self, tmp_path: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline

        with pytest.raises(FileNotFoundError):
            RetrievalPipeline(index_dir=tmp_path)

    @patch("src.retrieval.pipeline.embed_texts")
    def test_pipeline_vector_only(self, mock_embed: MagicMock, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline, SearchStrategy

        mock_embed.return_value = [np.random.default_rng(42).standard_normal(8).astype(np.float32).tolist()]
        pipeline = RetrievalPipeline(index_dir=index_dir)
        results = pipeline.search("청년 월세", strategy=SearchStrategy.VECTOR_ONLY)
        assert len(results) > 0
        mock_embed.assert_called_once()

    def test_pipeline_bm25_only(self, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline, SearchStrategy

        pipeline = RetrievalPipeline(index_dir=index_dir)
        results = pipeline.search("청년 월세", strategy=SearchStrategy.BM25_ONLY)
        assert len(results) > 0

    @patch("src.retrieval.pipeline.embed_texts")
    def test_pipeline_hybrid(self, mock_embed: MagicMock, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline, SearchStrategy

        mock_embed.return_value = [np.random.default_rng(42).standard_normal(8).astype(np.float32).tolist()]
        pipeline = RetrievalPipeline(index_dir=index_dir)
        results = pipeline.search("청년 월세", strategy=SearchStrategy.HYBRID, top_k=3)
        assert len(results) <= 3

    @patch("src.retrieval.pipeline.rerank")
    @patch("src.retrieval.pipeline.embed_texts")
    def test_pipeline_hybrid_rerank(self, mock_embed: MagicMock, mock_rerank: MagicMock, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline, SearchStrategy

        mock_embed.return_value = [np.random.default_rng(42).standard_normal(8).astype(np.float32).tolist()]
        mock_rerank.return_value = [
            SearchResult(content="reranked", score=0.9, metadata={}, rank=0),
        ]
        pipeline = RetrievalPipeline(index_dir=index_dir)
        results = pipeline.search("청년 월세", strategy=SearchStrategy.HYBRID_RERANK)
        assert len(results) == 1
        assert results[0].content == "reranked"
        mock_rerank.assert_called_once()

    def test_pipeline_strategy_string(self, index_dir: Path) -> None:
        from src.retrieval.pipeline import RetrievalPipeline

        pipeline = RetrievalPipeline(index_dir=index_dir)
        results = pipeline.search("청년", strategy="bm25_only")
        assert isinstance(results, list)
