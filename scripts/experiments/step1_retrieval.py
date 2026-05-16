"""실험 A: 검색 전략별 성능 비교 — 4가지 전략 × 100 QA 쌍.

측정: Context Precision, Context Recall, 검색 레이턴시.

사용법:
    python -m scripts.experiments.step1_retrieval [--resume]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scripts.experiments._common import (
    BASE_OUTPUT_DIR,
    CHECKPOINT_INTERVAL,
    DEFAULT_TOP_K,
    CostTracker,
    Timer,
    load_latest_checkpoint,
    load_qa_samples,
    make_run_id,
    save_checkpoint,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = BASE_OUTPUT_DIR / "step1_retrieval"
STRATEGIES = ["vector_only", "bm25_only", "hybrid", "hybrid_rerank"]


def main(resume: bool = False) -> Path:
    setup_logging("step1_retrieval", OUTPUT_DIR)
    logger.info("=== 실험 A: 검색 전략별 성능 비교 시작 ===")

    from src.retrieval.pipeline import RetrievalPipeline, SearchStrategy

    qa_samples = load_qa_samples()
    logger.info("QA 샘플 %d건 로드", len(qa_samples))

    pipeline = RetrievalPipeline()
    cost_tracker = CostTracker()

    checkpoint_dir = OUTPUT_DIR / "checkpoint"
    results: dict[str, list] = {s: [] for s in STRATEGIES}

    completed_keys: set[str] = set()
    if resume:
        ckpt, _ = load_latest_checkpoint(checkpoint_dir, "step1")
        if ckpt and isinstance(ckpt, dict) and "results" in ckpt:
            results = ckpt["results"]
            for strat, samples in results.items():
                for s in samples:
                    completed_keys.add(f"{strat}_{s['id']}")
            logger.info("체크포인트 복원: %d건 완료", len(completed_keys))

    total_work = len(STRATEGIES) * len(qa_samples)
    done = len(completed_keys)

    for strat_name in STRATEGIES:
        strategy = SearchStrategy(strat_name)

        for idx, sample in enumerate(qa_samples):
            sample_id = sample.get("id", f"q{idx:03d}")
            key = f"{strat_name}_{sample_id}"

            if key in completed_keys:
                continue

            question = sample.get("question", "")
            ground_truth = sample.get("ground_truth", "")

            with Timer() as t:
                search_results = pipeline.search(question, strategy=strategy, top_k=DEFAULT_TOP_K)

            contexts = [r.content for r in search_results]

            ragas_result = _evaluate_context_metrics(question, contexts, ground_truth)

            results[strat_name].append(
                {
                    "id": sample_id,
                    "question": question,
                    "contexts": contexts,
                    "retrieval_latency": t.elapsed,
                    "context_precision": ragas_result.get("context_precision"),
                    "context_recall": ragas_result.get("context_recall"),
                }
            )

            done += 1
            if done % CHECKPOINT_INTERVAL == 0:
                save_checkpoint({"results": results}, checkpoint_dir, "step1", done)
                logger.info("[%d/%d] 체크포인트 저장", done, total_work)

        logger.info("전략 %s 완료 (%d건)", strat_name, len(results[strat_name]))

    output = {
        "run_id": make_run_id("step1"),
        "config": {
            "top_k": DEFAULT_TOP_K,
            "strategies": STRATEGIES,
            "qa_count": len(qa_samples),
        },
        "results": results,
        "cost": cost_tracker.summary(),
    }

    output_path = OUTPUT_DIR / "retrieval_results.json"
    save_json(output, output_path)
    logger.info("=== 실험 A 완료: %s ===", output_path)
    return output_path


def _evaluate_context_metrics(question: str, contexts: list[str], ground_truth: str) -> dict:
    """RAGAS Context Precision/Recall만 계산."""
    try:
        from src.evaluation.ragas_metrics import evaluate_ragas

        result = evaluate_ragas(question, contexts, answer="", ground_truth=ground_truth)
        return {
            "context_precision": result.context_precision,
            "context_recall": result.context_recall,
        }
    except Exception:
        logger.exception("RAGAS Context 메트릭 평가 실패")
        return {"context_precision": None, "context_recall": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실험 A: 검색 전략별 성능 비교")
    parser.add_argument("--resume", action="store_true", help="체크포인트에서 이어서 실행")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()
    main(resume=args.resume)
