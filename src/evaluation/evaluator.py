"""3단계 통합 평가 오케스트레이터."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from src.evaluation import EvalResult, JudgeResult, RagasResult, SafetyResult

logger = logging.getLogger(__name__)

_DEFAULT_JUDGE_MODEL = "openai/gpt-4o-mini"
_CHECKPOINT_INTERVAL = 10


class RAGEvaluator:
    """RAGAS + LLM Judge + DeepEval 3단계 통합 평가."""

    def __init__(self, judge_model: str = _DEFAULT_JUDGE_MODEL) -> None:
        self.judge_model = judge_model

    def evaluate_single(
        self,
        question: str,
        contexts: list[str],
        answer: str,
        ground_truth: str,
    ) -> EvalResult:
        """단일 QA 쌍에 대해 3단계 평가 수행.

        Args:
            question: 사용자 질문.
            contexts: 검색된 컨텍스트.
            answer: 생성된 답변.
            ground_truth: 정답 레퍼런스.

        Returns:
            EvalResult with all three stages.
        """
        start = time.monotonic()

        ragas_result = self._run_ragas(question, contexts, answer, ground_truth)
        judge_result = self._run_judge(question, contexts, answer)
        safety_result = self._run_safety(question, contexts, answer)

        elapsed = round(time.monotonic() - start, 3)

        return EvalResult(
            ragas=ragas_result,
            judge=judge_result,
            safety=safety_result,
            latency=elapsed,
        )

    def evaluate_batch(
        self,
        samples: list[dict],
        checkpoint_dir: Path | None = None,
    ) -> list[dict]:
        """배치 평가 — 중간 체크포인트 저장.

        Args:
            samples: RAG 응답이 포함된 샘플 리스트.
                각 샘플은 id, question, answer, ground_truth, contexts 필드를 가져야 한다.
            checkpoint_dir: 체크포인트 저장 디렉토리. None이면 저장하지 않음.

        Returns:
            평가 결과 리스트 (각 항목에 eval_result 필드 추가).
        """
        results: list[dict] = []
        total = len(samples)

        for idx, sample in enumerate(samples):
            sample_id = sample.get("id", f"unknown_{idx}")

            if sample.get("error"):
                results.append({**sample, "eval_result": None, "eval_error": "응답 생성 실패"})
                logger.warning("[%d/%d] %s — 건너뜀 (응답 생성 실패)", idx + 1, total, sample_id)
                continue

            try:
                eval_result = self.evaluate_single(
                    question=sample.get("question", ""),
                    contexts=sample.get("contexts", []),
                    answer=sample.get("answer", ""),
                    ground_truth=sample.get("ground_truth", ""),
                )
                results.append(
                    {
                        **sample,
                        "eval_result": {
                            "ragas": _ragas_to_dict(eval_result.ragas),
                            "judge": _judge_to_dict(eval_result.judge),
                            "safety": _safety_to_dict(eval_result.safety),
                            "latency": eval_result.latency,
                        },
                    }
                )
                logger.info("[%d/%d] %s — 평가 완료 (%.1fs)", idx + 1, total, sample_id, eval_result.latency)

            except Exception:
                logger.exception("[%d/%d] %s — 평가 실패", idx + 1, total, sample_id)
                results.append({**sample, "eval_result": None, "eval_error": "평가 중 예외 발생"})

            if checkpoint_dir and (idx + 1) % _CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint(results, checkpoint_dir, idx + 1)

        return results

    def _run_ragas(self, question: str, contexts: list[str], answer: str, ground_truth: str) -> RagasResult | None:
        try:
            from src.evaluation.ragas_metrics import evaluate_ragas

            return evaluate_ragas(question, contexts, answer, ground_truth)
        except Exception:
            logger.exception("RAGAS 평가 실패")
            return None

    def _run_judge(self, question: str, contexts: list[str], answer: str) -> JudgeResult | None:
        try:
            from src.evaluation.llm_judge import judge_response

            return judge_response(question, contexts, answer, judge_model=self.judge_model)
        except Exception:
            logger.exception("LLM Judge 평가 실패")
            return None

    def _run_safety(self, question: str, contexts: list[str], answer: str) -> SafetyResult | None:
        try:
            from src.evaluation.safety_metrics import evaluate_safety

            return evaluate_safety(question, contexts, answer)
        except Exception:
            logger.exception("DeepEval 안전성 평가 실패")
            return None

    @staticmethod
    def _save_checkpoint(results: list[dict], checkpoint_dir: Path, count: int) -> None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = checkpoint_dir / f"checkpoint_{count}.json"
        with open(path, "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        logger.info("체크포인트 저장: %s (%d건)", path, count)


def _ragas_to_dict(result: RagasResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "faithfulness": result.faithfulness,
        "answer_relevancy": result.answer_relevancy,
        "context_precision": result.context_precision,
        "context_recall": result.context_recall,
    }


def _judge_to_dict(result: JudgeResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "citation_accuracy": result.citation_accuracy,
        "completeness": result.completeness,
        "readability": result.readability,
        "average": result.average,
        "raw_scores": list(result.raw_scores),
    }


def _safety_to_dict(result: SafetyResult | None) -> dict | None:
    if result is None:
        return None
    return {"hallucination_score": result.hallucination_score}
