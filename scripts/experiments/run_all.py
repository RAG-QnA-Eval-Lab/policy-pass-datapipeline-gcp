"""실험 파이프라인 오케스트레이터 — step1~step6 순차 실행.

사용법:
    python -m scripts.experiments.run_all                 # 전체 실행
    python -m scripts.experiments.run_all --start step3   # step3부터 실행
    python -m scripts.experiments.run_all --only step4 step5  # 특정 단계만 실행
    python -m scripts.experiments.run_all --resume         # 체크포인트에서 이어서
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from scripts.experiments._common import BASE_OUTPUT_DIR, setup_logging

logger = logging.getLogger(__name__)

STEP_ORDER = ["step1", "step2", "step3", "step4", "step5", "step6"]

STEP_DESCRIPTIONS = {
    "step1": "실험 A: 검색 전략별 성능 비교",
    "step2": "실험 B: 멀티 LLM 답변 생성",
    "step3": "실험 B+C+D: 3단계 평가 (2종 Judge)",
    "step4": "실험 C: Judge 비용-성능 비교 (통계 분석)",
    "step5": "실험 D+E: Position Bias + 교차 상관 + 탐지율 분석",
    "step6": "논문 표·그림 생성",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="실험 파이프라인 오케스트레이터")
    parser.add_argument("--start", choices=STEP_ORDER, help="이 단계부터 실행")
    parser.add_argument("--only", nargs="+", choices=STEP_ORDER, help="특정 단계만 실행")
    parser.add_argument("--resume", action="store_true", help="체크포인트에서 이어서 실행")
    parser.add_argument("--dry-run", action="store_true", help="실행 계획만 출력")
    args = parser.parse_args()

    setup_logging("run_all", BASE_OUTPUT_DIR)

    steps = _resolve_steps(args.start, args.only)

    logger.info("=" * 60)
    logger.info("실험 파이프라인 실행 계획")
    logger.info("=" * 60)
    for step in steps:
        logger.info("  %s — %s", step, STEP_DESCRIPTIONS[step])
    if args.resume:
        logger.info("  (체크포인트 이어서 실행 모드)")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("(dry-run 모드 — 실행하지 않음)")
        return

    results: dict[str, dict] = {}
    total_start = time.monotonic()

    for step in steps:
        logger.info("")
        logger.info(">>> %s: %s 시작 <<<", step, STEP_DESCRIPTIONS[step])
        step_start = time.monotonic()

        try:
            output_path = _run_step(step, resume=args.resume)
            elapsed = round(time.monotonic() - step_start, 1)
            results[step] = {"status": "success", "output": str(output_path), "elapsed_s": elapsed}
            logger.info(">>> %s 완료 (%.1fs) — %s <<<", step, elapsed, output_path)

        except FileNotFoundError as e:
            elapsed = round(time.monotonic() - step_start, 1)
            results[step] = {"status": "skipped", "reason": str(e), "elapsed_s": elapsed}
            logger.warning(">>> %s 건너뜀: %s <<<", step, e)

        except Exception:
            elapsed = round(time.monotonic() - step_start, 1)
            results[step] = {"status": "failed", "elapsed_s": elapsed}
            logger.exception(">>> %s 실패 <<<", step)
            logger.error("파이프라인 중단. --start %s 로 이어서 실행 가능", step)
            sys.exit(1)

    total_elapsed = round(time.monotonic() - total_start, 1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("실험 파이프라인 완료 (총 %.1fs)", total_elapsed)
    logger.info("=" * 60)
    for step, info in results.items():
        logger.info("  %s: %s (%.1fs)", step, info["status"], info["elapsed_s"])


def _resolve_steps(start: str | None, only: list[str] | None) -> list[str]:
    if only:
        return [s for s in STEP_ORDER if s in only]
    if start:
        idx = STEP_ORDER.index(start)
        return STEP_ORDER[idx:]
    return list(STEP_ORDER)


def _run_step(step: str, resume: bool = False) -> Path | tuple[Path, ...]:
    if step == "step1":
        from scripts.experiments.step1_retrieval import main as step1_main

        return step1_main(resume=resume)

    if step == "step2":
        from scripts.experiments.step2_generation import main as step2_main

        return step2_main(resume=resume)

    if step == "step3":
        from scripts.experiments.step3_evaluation import main as step3_main

        return step3_main(resume=resume)

    if step == "step4":
        from scripts.experiments.step4_judge_comparison import main as step4_main

        return step4_main()

    if step == "step5":
        from scripts.experiments.step5_analysis import main as step5_main

        return step5_main()

    if step == "step6":
        from scripts.experiments.step6_tables_figures import main as step6_main

        return step6_main()

    raise ValueError(f"알 수 없는 단계: {step}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    main()
