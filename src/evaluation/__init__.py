"""3단계 평가 시스템 — RAGAS 정량 + LLM Judge 정성 + DeepEval 안전성."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RagasResult:
    """RAGAS v0.4 정량 평가 결과."""

    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None


@dataclass(frozen=True)
class JudgeResult:
    """LLM-as-a-Judge 정성 평가 결과 (각 항목 1-5점)."""

    citation_accuracy: float = 0.0
    completeness: float = 0.0
    readability: float = 0.0
    average: float = 0.0
    raw_scores: tuple[dict[str, int], ...] = ()


@dataclass(frozen=True)
class SafetyResult:
    """DeepEval 안전성 평가 결과."""

    hallucination_score: float | None = None


@dataclass(frozen=True)
class EvalResult:
    """3단계 통합 평가 결과."""

    ragas: RagasResult | None = None
    judge: JudgeResult | None = None
    safety: SafetyResult | None = None
    latency: float = 0.0
