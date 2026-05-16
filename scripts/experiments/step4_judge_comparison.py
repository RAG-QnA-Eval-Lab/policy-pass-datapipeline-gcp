"""실험 C: LLM Judge 비용-성능 분석 — Gemini 2.5 Pro vs GPT-4o-mini 통계 비교.

LLM 호출 없음 — step3의 결과 JSON 2개를 비교 분석.

사용법:
    python -m scripts.experiments.step4_judge_comparison
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, spearmanr

from scripts.experiments._common import (
    BASE_OUTPUT_DIR,
    load_json,
    make_run_id,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = BASE_OUTPUT_DIR / "step4_judge_comparison"

EVAL_PRIMARY_PATH = BASE_OUTPUT_DIR / "step3_evaluation" / "eval_gpt4o_mini_judge.json"
EVAL_EXPENSIVE_PATH = BASE_OUTPUT_DIR / "step3_evaluation" / "eval_gemini_pro_judge.json"

JUDGE_METRICS = ["citation_accuracy", "completeness", "readability", "average"]


def main() -> Path:
    setup_logging("step4_judge_comparison", OUTPUT_DIR)
    logger.info("=== 실험 C: Judge 비용-성능 비교 시작 ===")

    primary_data = load_json(EVAL_PRIMARY_PATH)
    expensive_data = load_json(EVAL_EXPENSIVE_PATH)

    pairs = _align_samples(primary_data["results"], expensive_data["results"])
    logger.info("비교 가능한 샘플 쌍: %d건", len(pairs))

    agreement = _compute_agreement_metrics(pairs)
    cost_comparison = _compute_cost_comparison(primary_data, expensive_data)
    per_condition = _compute_per_condition(pairs)

    output = {
        "run_id": make_run_id("step4"),
        "config": {
            "primary_judge": "openai/gpt-4o-mini",
            "expensive_judge": "vertex_ai/gemini-3.1-pro-preview",
            "sample_count": len(pairs),
        },
        "agreement_metrics": agreement,
        "cost_comparison": cost_comparison,
        "per_condition": per_condition,
    }

    output_path = OUTPUT_DIR / "judge_comparison.json"
    save_json(output, output_path)
    logger.info("=== 실험 C 완료: %s ===", output_path)
    return output_path


def _align_samples(primary_results: list[dict], expensive_results: list[dict]) -> list[tuple[dict, dict]]:
    expensive_map: dict[str, dict] = {}
    for s in expensive_results:
        key = f"{s.get('condition', '')}_{s.get('id', '')}"
        expensive_map[key] = s

    pairs = []
    for s in primary_results:
        key = f"{s.get('condition', '')}_{s.get('id', '')}"
        if key in expensive_map:
            p_eval = s.get("eval")
            e_eval = expensive_map[key].get("eval")
            if not (p_eval and e_eval):
                continue
            p_judge = p_eval.get("judge")
            e_judge = e_eval.get("judge")
            if not (p_judge and e_judge):
                continue
            if p_judge.get("average", 0) == 0 or e_judge.get("average", 0) == 0:
                continue
            pairs.append((s, expensive_map[key]))
    return pairs


def _compute_agreement_metrics(pairs: list[tuple[dict, dict]]) -> dict:
    result = {}

    for metric in JUDGE_METRICS:
        primary_scores = [p["eval"]["judge"][metric] for p, _ in pairs]
        expensive_scores = [e["eval"]["judge"][metric] for _, e in pairs]

        pa = np.array(primary_scores)
        ea = np.array(expensive_scores)

        tau, tau_p = kendalltau(pa, ea)
        rho, rho_p = spearmanr(pa, ea)
        mae = float(np.mean(np.abs(pa - ea)))
        perfect = float(np.mean(np.round(pa) == np.round(ea)))

        class_primary = [_to_class(v) for v in primary_scores]
        class_expensive = [_to_class(v) for v in expensive_scores]
        class_agr = float(np.mean([a == b for a, b in zip(class_primary, class_expensive)]))

        result[metric] = {
            "kendall_tau": round(float(tau), 4),
            "kendall_p": round(float(tau_p), 6),
            "spearman_rho": round(float(rho), 4),
            "spearman_p": round(float(rho_p), 6),
            "mae": round(mae, 4),
            "perfect_agreement_rate": round(perfect, 4),
            "class_agreement_rate": round(class_agr, 4),
        }

        logger.info(
            "  %s: τ=%.3f, ρ=%.3f, MAE=%.3f, Perfect=%.1f%%, Class=%.1f%%",
            metric,
            tau,
            rho,
            mae,
            perfect * 100,
            class_agr * 100,
        )

    return result


def _to_class(score: float) -> str:
    if score < 2.5:
        return "low"
    if score < 3.5:
        return "mid"
    return "high"


def _compute_cost_comparison(primary_data: dict, expensive_data: dict) -> dict:
    primary_cost = primary_data.get("cost", {})
    expensive_cost = expensive_data.get("cost", {})

    p_usd = primary_cost.get("estimated_usd", 0.0)
    e_usd = expensive_cost.get("estimated_usd", 0.0)

    return {
        "gpt-4o-mini": {
            "estimated_usd": p_usd,
            "total_calls": primary_cost.get("total_calls", 0),
        },
        "gemini-3.1-pro": {
            "estimated_usd": e_usd,
            "total_calls": expensive_cost.get("total_calls", 0),
        },
        "cost_ratio": round(e_usd / p_usd, 1) if p_usd > 0 else 0.0,
    }


def _compute_per_condition(pairs: list[tuple[dict, dict]]) -> dict:
    by_condition: dict[str, list[tuple[dict, dict]]] = {}
    for p, e in pairs:
        cond = p.get("condition", "unknown")
        by_condition.setdefault(cond, []).append((p, e))

    result = {}
    for cond, cond_pairs in by_condition.items():
        cond_agreement = {}
        for metric in JUDGE_METRICS:
            pa = [p["eval"]["judge"][metric] for p, _ in cond_pairs]
            ea = [e["eval"]["judge"][metric] for _, e in cond_pairs]
            if len(pa) < 3:
                continue
            tau, _ = kendalltau(pa, ea)
            rho, _ = spearmanr(pa, ea)
            mae = float(np.mean(np.abs(np.array(pa) - np.array(ea))))
            cond_agreement[metric] = {
                "kendall_tau": round(float(tau), 4),
                "spearman_rho": round(float(rho), 4),
                "mae": round(mae, 4),
                "count": len(pa),
            }
        result[cond] = cond_agreement

    return result


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    main()
