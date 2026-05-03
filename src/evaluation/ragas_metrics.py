"""Stage 1 — RAGAS v0.4 정량 평가."""

from __future__ import annotations

import asyncio
import logging

from src.evaluation import RagasResult

logger = logging.getLogger(__name__)


async def _score_metric(metric: object, sample: object) -> float | None:
    """단일 메트릭 비동기 평가 — 실패 시 None 반환."""
    name = type(metric).__name__
    try:
        score = await metric.single_turn_ascore(sample)  # type: ignore[attr-defined]
        logger.debug("메트릭 %s: %.4f", name, score)
        return float(score)
    except Exception:
        logger.exception("메트릭 %s 평가 실패", name)
        return None


def evaluate_ragas(
    question: str,
    contexts: list[str],
    answer: str,
    ground_truth: str,
) -> RagasResult:
    """RAGAS v0.4 정량 평가 수행.

    Args:
        question: 사용자 질문.
        contexts: 검색된 컨텍스트 목록.
        answer: LLM이 생성한 답변.
        ground_truth: 정답 레퍼런스.

    Returns:
        RagasResult with metric scores (None if metric failed).
    """
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics.collections import (
        ContextPrecision,
        ContextRecall,
        Faithfulness,
        ResponseRelevancy,
    )

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
        reference=ground_truth,
    )

    metrics = {
        "faithfulness": Faithfulness(),
        "answer_relevancy": ResponseRelevancy(),
        "context_precision": ContextPrecision(),
        "context_recall": ContextRecall(),
    }

    async def _run_all() -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for key, metric in metrics.items():
            result[key] = await _score_metric(metric, sample)
        return result

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            scores = pool.submit(asyncio.run, _run_all()).result()
    else:
        scores = asyncio.run(_run_all())

    return RagasResult(
        faithfulness=scores["faithfulness"],
        answer_relevancy=scores["answer_relevancy"],
        context_precision=scores["context_precision"],
        context_recall=scores["context_recall"],
    )
