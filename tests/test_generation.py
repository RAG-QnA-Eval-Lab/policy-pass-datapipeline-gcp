"""생성 시스템 테스트 — llm_client, prompt, pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

from src.generation import LLMResponse, RAGResponse
from src.generation.prompt import (
    SYSTEM_PROMPT,
    build_no_rag_prompt,
    build_rag_prompt,
)
from src.retrieval import SearchResult

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture()
def sample_search_results() -> list[SearchResult]:
    return [
        SearchResult(
            content="청년 월세 지원 정책입니다. 월 최대 20만원 지원.",
            score=0.95,
            metadata={"title": "월세지원", "category": "housing", "source_name": "온통청년"},
            rank=0,
        ),
        SearchResult(
            content="국민취업지원제도는 취업 준비 청년을 위한 정책입니다.",
            score=0.85,
            metadata={"title": "국민취업지원", "category": "employment", "source_name": "고용노동부"},
            rank=1,
        ),
    ]


@pytest.fixture()
def mock_llm_response() -> LLMResponse:
    return LLMResponse(
        content="청년 월세 한시 특별지원은 월 최대 20만원을 지원합니다. [출처: 월세지원, 온통청년]",
        model="gpt-4o-mini",
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=200,
        latency=0.5,
    )


@pytest.fixture()
def index_dir(tmp_path: Path) -> Path:
    """테스트용 FAISS 인덱스 디렉토리."""
    metadata = [
        {"content": "청년 월세 지원 정책입니다.", "title": "월세지원", "category": "housing"},
        {"content": "국민취업지원제도 안내.", "title": "국민취업지원", "category": "employment"},
        {"content": "청년 전세자금 대출 정책.", "title": "전세대출", "category": "housing"},
    ]
    dim = 8
    vectors = np.random.default_rng(42).standard_normal((len(metadata), dim)).astype(np.float32)
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    faiss.write_index(index, str(tmp_path / "faiss.index"))
    with open(tmp_path / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)
    return tmp_path


# ──────────────────────────────────────────────
# LLMResponse / RAGResponse dataclasses
# ──────────────────────────────────────────────


class TestDataclasses:
    def test_llm_response_frozen(self) -> None:
        resp = LLMResponse(content="test", model="gpt-4o-mini")
        with pytest.raises(AttributeError):
            resp.content = "modified"  # type: ignore[misc]

    def test_llm_response_defaults(self) -> None:
        resp = LLMResponse(content="test", model="m")
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
        assert resp.total_tokens == 0
        assert resp.latency == 0.0

    def test_rag_response_frozen(self) -> None:
        resp = RAGResponse(answer="test")
        with pytest.raises(AttributeError):
            resp.answer = "modified"  # type: ignore[misc]

    def test_rag_response_defaults(self) -> None:
        resp = RAGResponse(answer="test")
        assert resp.sources == []
        assert resp.model == ""
        assert resp.search_strategy == ""
        assert resp.llm_response is None


# ──────────────────────────────────────────────
# Prompt Builder
# ──────────────────────────────────────────────


class TestPrompt:
    def test_build_rag_prompt_structure(self, sample_search_results: list[SearchResult]) -> None:
        messages = build_rag_prompt("청년 월세 지원은?", sample_search_results)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert SYSTEM_PROMPT in messages[0]["content"]

    def test_build_rag_prompt_contains_context(self, sample_search_results: list[SearchResult]) -> None:
        messages = build_rag_prompt("청년 월세 지원은?", sample_search_results)
        user_content = messages[1]["content"]
        assert "월세지원" in user_content
        assert "온통청년" in user_content
        assert "청년 월세 지원은?" in user_content

    def test_build_rag_prompt_numbering(self, sample_search_results: list[SearchResult]) -> None:
        messages = build_rag_prompt("질문", sample_search_results)
        user_content = messages[1]["content"]
        assert "[1]" in user_content
        assert "[2]" in user_content

    def test_build_rag_prompt_empty_contexts(self) -> None:
        messages = build_rag_prompt("질문", [])
        user_content = messages[1]["content"]
        assert "관련 정책 문서를 찾지 못했습니다" in user_content

    def test_build_no_rag_prompt(self) -> None:
        messages = build_no_rag_prompt("청년 월세 지원은?")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "청년 월세 지원은?"

    def test_build_rag_prompt_metadata_missing_fields(self) -> None:
        results = [SearchResult(content="내용", score=0.5, metadata={}, rank=0)]
        messages = build_rag_prompt("질문", results)
        user_content = messages[1]["content"]
        assert "제목 없음" in user_content


# ──────────────────────────────────────────────
# LLM Client
# ──────────────────────────────────────────────


class TestLLMClient:
    @patch("src.generation.llm_client.completion")
    def test_generate_success(self, mock_completion: MagicMock) -> None:
        from src.generation.llm_client import generate

        mock_choice = MagicMock()
        mock_choice.message.content = "답변입니다."
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 30
        mock_usage.total_tokens = 130
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o-mini"
        mock_completion.return_value = mock_response

        result = generate(
            messages=[{"role": "user", "content": "질문"}],
            model="openai/gpt-4o-mini",
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "답변입니다."
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 30
        assert result.total_tokens == 130
        assert result.latency >= 0
        mock_completion.assert_called_once()

    @patch("src.generation.llm_client.completion")
    def test_generate_empty_content(self, mock_completion: MagicMock) -> None:
        from src.generation.llm_client import generate

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None
        mock_response.model = "gpt-4o-mini"
        mock_completion.return_value = mock_response

        result = generate(messages=[{"role": "user", "content": "질문"}])
        assert result.content == ""
        assert result.prompt_tokens == 0

    @patch("src.generation.llm_client.completion")
    def test_generate_retry_on_rate_limit(self, mock_completion: MagicMock) -> None:
        from litellm.exceptions import RateLimitError

        from src.generation.llm_client import generate

        mock_choice = MagicMock()
        mock_choice.message.content = "재시도 성공"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_usage.total_tokens = 15
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o-mini"

        mock_completion.side_effect = [
            RateLimitError("rate limited", "openai", "gpt-4o-mini"),
            mock_response,
        ]

        result = generate(messages=[{"role": "user", "content": "질문"}])
        assert result.content == "재시도 성공"
        assert mock_completion.call_count == 2

    @patch("src.generation.llm_client.completion")
    def test_generate_max_retries_exceeded(self, mock_completion: MagicMock) -> None:
        from litellm.exceptions import RateLimitError

        from src.generation.llm_client import generate

        mock_completion.side_effect = RateLimitError("rate limited", "openai", "gpt-4o-mini")

        with pytest.raises(RuntimeError, match="재시도 초과"):
            generate(messages=[{"role": "user", "content": "질문"}])


# ──────────────────────────────────────────────
# RAG Pipeline
# ──────────────────────────────────────────────


class TestRAGPipeline:
    @patch("src.generation.pipeline.generate")
    @patch("src.generation.pipeline.RetrievalPipeline")
    def test_run_rag(
        self, mock_retrieval_cls: MagicMock, mock_generate: MagicMock, mock_llm_response: LLMResponse
    ) -> None:
        from src.generation.pipeline import RAGPipeline

        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = [
            SearchResult(content="월세 지원", score=0.9, metadata={"title": "월세지원", "category": "housing"}, rank=0),
        ]
        mock_retrieval_cls.return_value = mock_retrieval
        mock_generate.return_value = mock_llm_response

        pipeline = RAGPipeline(index_dir="/fake")
        result = pipeline.run("청년 월세 지원은?", model="openai/gpt-4o-mini")

        assert isinstance(result, RAGResponse)
        assert result.answer == mock_llm_response.content
        assert len(result.sources) == 1
        assert result.sources[0]["title"] == "월세지원"
        assert result.model == "openai/gpt-4o-mini"
        assert result.llm_response == mock_llm_response
        mock_retrieval.search.assert_called_once()
        mock_generate.assert_called_once()

    @patch("src.generation.pipeline.generate")
    def test_run_no_rag(self, mock_generate: MagicMock, mock_llm_response: LLMResponse) -> None:
        from src.generation.pipeline import RAGPipeline

        mock_generate.return_value = mock_llm_response

        with patch("src.generation.pipeline.RetrievalPipeline"):
            pipeline = RAGPipeline(index_dir="/fake")
            result = pipeline.run_no_rag("청년 월세 지원은?")

        assert isinstance(result, RAGResponse)
        assert result.sources == []
        assert result.search_strategy == "no_rag"
        assert result.retrieval_latency == 0.0
        mock_generate.assert_called_once()

    @patch("src.generation.pipeline.generate")
    @patch("src.generation.pipeline.RetrievalPipeline")
    def test_run_empty_search_results(self, mock_retrieval_cls: MagicMock, mock_generate: MagicMock) -> None:
        from src.generation.pipeline import RAGPipeline

        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = []
        mock_retrieval_cls.return_value = mock_retrieval
        mock_generate.return_value = LLMResponse(content="정보 없음", model="gpt-4o-mini")

        pipeline = RAGPipeline(index_dir="/fake")
        result = pipeline.run("알 수 없는 정책")

        assert result.answer == "정보 없음"
        assert result.sources == []

    @patch("src.generation.pipeline.generate")
    @patch("src.generation.pipeline.RetrievalPipeline")
    def test_run_uses_default_model(self, mock_retrieval_cls: MagicMock, mock_generate: MagicMock) -> None:
        from src.generation.pipeline import RAGPipeline

        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = []
        mock_retrieval_cls.return_value = mock_retrieval
        mock_generate.return_value = LLMResponse(content="ok", model="custom-model")

        pipeline = RAGPipeline(index_dir="/fake", default_model="anthropic/claude-sonnet-4-20250514")
        pipeline.run("질문")

        call_kwargs = mock_generate.call_args
        assert call_kwargs[1]["model"] == "anthropic/claude-sonnet-4-20250514"

    @patch("src.generation.pipeline.generate")
    @patch("src.generation.pipeline.RetrievalPipeline")
    def test_run_model_override(self, mock_retrieval_cls: MagicMock, mock_generate: MagicMock) -> None:
        from src.generation.pipeline import RAGPipeline

        mock_retrieval = MagicMock()
        mock_retrieval.search.return_value = []
        mock_retrieval_cls.return_value = mock_retrieval
        mock_generate.return_value = LLMResponse(content="ok", model="gemini")

        pipeline = RAGPipeline(index_dir="/fake", default_model="openai/gpt-4o-mini")
        pipeline.run("질문", model="gemini/gemini-2.0-flash")

        call_kwargs = mock_generate.call_args
        assert call_kwargs[1]["model"] == "gemini/gemini-2.0-flash"


# ──────────────────────────────────────────────
# _resolve_model helper
# ──────────────────────────────────────────────


class TestResolveModel:
    def test_resolve_known_key(self) -> None:
        from src.generation.pipeline import _resolve_model

        assert _resolve_model("gpt-4o-mini") == "openai/gpt-4o-mini"

    def test_resolve_unknown_passthrough(self) -> None:
        from src.generation.pipeline import _resolve_model

        assert _resolve_model("openai/gpt-4o-mini") == "openai/gpt-4o-mini"
