"""평가 엔드포인트."""

import logging

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_api_key
from src.api.rate_limit import limiter
from src.api.schemas import (
    EvalRequest,
    EvalResponse,
    EvalResultItem,
    JudgeScores,
    RagasScores,
    SafetyScores,
)
from src.evaluation.evaluator import RAGEvaluator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["evaluate"], dependencies=[Depends(require_api_key)])


@router.post("/evaluate", response_model=EvalResponse)
@limiter.limit("5/minute")
def evaluate(request: Request, body: EvalRequest) -> EvalResponse:
    evaluator = RAGEvaluator(judge_model=body.judge_model or "openai/gpt-4o-mini")

    results: list[EvalResultItem] = []
    errors = 0

    for sample in body.samples:
        try:
            er = evaluator.evaluate_single(
                question=sample.question,
                contexts=sample.contexts,
                answer=sample.answer,
                ground_truth=sample.ground_truth,
            )
            results.append(
                EvalResultItem(
                    id=sample.id,
                    ragas=RagasScores(
                        faithfulness=er.ragas.faithfulness,
                        answer_relevancy=er.ragas.answer_relevancy,
                        context_precision=er.ragas.context_precision,
                        context_recall=er.ragas.context_recall,
                    ) if er.ragas else None,
                    judge=JudgeScores(
                        citation_accuracy=er.judge.citation_accuracy,
                        completeness=er.judge.completeness,
                        readability=er.judge.readability,
                        average=er.judge.average,
                    ) if er.judge else None,
                    safety=SafetyScores(
                        hallucination_score=er.safety.hallucination_score,
                    ) if er.safety else None,
                    latency=er.latency,
                )
            )
        except Exception:
            logger.exception("Eval failed for sample %s", sample.id)
            errors += 1
            results.append(EvalResultItem(id=sample.id, error="evaluation_failed"))

    return EvalResponse(
        results=results,
        total=len(body.samples),
        evaluated=len(body.samples) - errors,
        errors=errors,
    )
