"""실험 D + E + 탐지율 분석 — Position Bias, 교차 상관, 단독 vs 조합 탐지율.

LLM 호출 없음 — step3 결과 JSON의 순수 통계 분석.

사용법:
    python -m scripts.experiments.step5_analysis
"""

from __future__ import annotations

import logging
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr, wilcoxon

from scripts.experiments._common import (
    BASE_OUTPUT_DIR,
    load_json,
    make_run_id,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = BASE_OUTPUT_DIR / "step5_analysis"
EVAL_PATH = BASE_OUTPUT_DIR / "step3_evaluation" / "eval_gpt4o_mini_judge.json"

FAITHFULNESS_THRESHOLD = 0.5
JUDGE_AVG_THRESHOLD = 3.0
HALLUCINATION_THRESHOLD = 0.5


def main() -> tuple[Path, Path, Path]:
    setup_logging("step5_analysis", OUTPUT_DIR)
    logger.info("=== 실험 D+E + 탐지율 분석 시작 ===")

    eval_data = load_json(EVAL_PATH)
    samples = [s for s in eval_data.get("results", []) if s.get("eval")]
    logger.info("분석 대상: %d건", len(samples))

    bias_path = _analyze_position_bias(samples)
    corr_path = _analyze_cross_correlation(samples)
    detect_path = _analyze_detection_coverage(samples)

    logger.info("=== 실험 D+E + 탐지율 분석 완료 ===")
    return bias_path, corr_path, detect_path


def _analyze_position_bias(samples: list[dict]) -> Path:
    """실험 D: Position Bias 완화 효과 검증."""
    logger.info("--- 실험 D: Position Bias 분석 ---")

    valid_samples = []
    for s in samples:
        judge = s.get("eval", {}).get("judge")
        if not judge:
            continue
        raw = judge.get("raw_scores", {})
        orig = raw.get("original_order", {})
        shuf = raw.get("shuffled_order", {})
        if orig and shuf:
            valid_samples.append((orig, shuf))

    if not valid_samples:
        logger.warning("raw_scores 데이터 없음 — Position Bias 분석 건너뜀")
        empty = {"error": "raw_scores 데이터 없음"}
        path = OUTPUT_DIR / "position_bias.json"
        save_json(empty, path)
        return path

    logger.info("Position Bias 분석 대상: %d건", len(valid_samples))

    metrics = ["citation_accuracy", "completeness", "readability"]
    per_metric: dict[str, dict] = {}

    for metric in metrics:
        originals = [orig[metric] for orig, _ in valid_samples if metric in orig]
        shuffleds = [shuf[metric] for _, shuf in valid_samples if metric in shuf]

        n = min(len(originals), len(shuffleds))
        originals = originals[:n]
        shuffleds = shuffleds[:n]

        if n < 5:
            continue

        deltas = [abs(o - s) for o, s in zip(originals, shuffleds)]
        delta_dist = {}
        for d in deltas:
            delta_dist[str(d)] = delta_dist.get(str(d), 0) + 1

        try:
            stat, p_val = wilcoxon(originals, shuffleds, alternative="two-sided")
        except ValueError:
            stat, p_val = 0.0, 1.0

        ge1_count = sum(1 for d in deltas if d >= 1)

        per_metric[metric] = {
            "mean_abs_delta": round(float(np.mean(deltas)), 4),
            "std_abs_delta": round(float(np.std(deltas)), 4),
            "max_delta": int(max(deltas)),
            "delta_distribution": delta_dist,
            "ge1_delta_count": ge1_count,
            "ge1_delta_rate": round(ge1_count / n, 4),
            "wilcoxon_statistic": round(float(stat), 2),
            "wilcoxon_p_value": round(float(p_val), 6),
            "sample_count": n,
        }

        logger.info(
            "  %s: mean_|Δ|=%.3f, ≥1점차=%d/%d (%.1f%%), Wilcoxon p=%.4f",
            metric, np.mean(deltas), ge1_count, n, ge1_count / n * 100, p_val,
        )

    all_orig = []
    all_avg = []
    for orig, shuf in valid_samples:
        orig_vals = [orig.get(m, 0) for m in metrics]
        shuf_vals = [shuf.get(m, 0) for m in metrics]
        if all(orig_vals) and all(shuf_vals):
            all_orig.append(float(np.mean(orig_vals)))
            all_avg.append(float(np.mean([(o + s) / 2 for o, s in zip(orig_vals, shuf_vals)])))

    variance_comparison = {}
    if all_orig:
        sv = float(np.var(all_orig))
        av = float(np.var(all_avg))
        variance_comparison = {
            "single_eval_variance": round(sv, 4),
            "averaged_variance": round(av, 4),
            "variance_reduction_pct": round((sv - av) / sv * 100, 2) if sv > 0 else 0.0,
        }

    output = {
        "run_id": make_run_id("step5_bias"),
        "per_metric_delta": per_metric,
        "variance_comparison": variance_comparison,
        "total_samples": len(valid_samples),
    }

    path = OUTPUT_DIR / "position_bias.json"
    save_json(output, path)
    logger.info("Position Bias 결과 저장: %s", path)
    return path


def _analyze_cross_correlation(samples: list[dict]) -> Path:
    """실험 E: 3단계 교차 상관 분석."""
    logger.info("--- 실험 E: 교차 상관 분석 ---")

    faithfulness_vals = []
    judge_avg_vals = []
    halluc_vals = []
    relevancy_vals = []
    completeness_vals = []
    readability_vals = []

    for s in samples:
        ev = s.get("eval", {})
        ragas = ev.get("ragas")
        judge = ev.get("judge")
        safety = ev.get("safety")

        if not ragas or not judge or not safety:
            continue
        if ragas.get("faithfulness") is None or judge.get("average") is None:
            continue
        if safety.get("hallucination_score") is None:
            continue

        faithfulness_vals.append(ragas["faithfulness"])
        judge_avg_vals.append(judge["average"])
        halluc_vals.append(safety["hallucination_score"])
        relevancy_vals.append(ragas.get("answer_relevancy", 0.0) or 0.0)
        completeness_vals.append(judge.get("completeness", 0.0))
        readability_vals.append(judge.get("readability", 0.0))

    logger.info("상관 분석 대상: %d건", len(faithfulness_vals))

    def _corr(a: list[float], b: list[float], name: str) -> dict:
        if len(a) < 5:
            return {"spearman_rho": None, "p_value": None, "interpretation": "insufficient_data"}
        rho, p = spearmanr(a, b)
        interp = _interpret_rho(float(rho))
        logger.info("  %s: ρ=%.3f (p=%.4f) — %s", name, rho, p, interp)
        return {
            "spearman_rho": round(float(rho), 4),
            "p_value": round(float(p), 6),
            "interpretation": interp,
        }

    overall = {
        "ragas_faith_vs_judge_avg": _corr(faithfulness_vals, judge_avg_vals, "Faith↔Judge"),
        "ragas_faith_vs_safety_hall": _corr(faithfulness_vals, halluc_vals, "Faith↔Halluc"),
        "judge_avg_vs_safety_hall": _corr(judge_avg_vals, halluc_vals, "Judge↔Halluc"),
        "ragas_relevancy_vs_judge_completeness": _corr(relevancy_vals, completeness_vals, "Relevancy↔Complete"),
        "judge_readability_vs_judge_avg": _corr(readability_vals, judge_avg_vals, "Read↔JudgeAvg"),
        "judge_readability_vs_ragas_faith": _corr(readability_vals, faithfulness_vals, "Read↔Faith"),
    }

    by_condition: dict[str, list[dict]] = {}
    for s in samples:
        cond = s.get("condition", "unknown")
        by_condition.setdefault(cond, []).append(s)

    per_condition = {}
    for cond, cond_samples in by_condition.items():
        f_vals = []
        j_vals = []
        h_vals = []
        for s in cond_samples:
            ev = s.get("eval", {})
            r = ev.get("ragas")
            j = ev.get("judge")
            sf = ev.get("safety")
            if r and j and sf and r.get("faithfulness") is not None and j.get("average") is not None:
                f_vals.append(r["faithfulness"])
                j_vals.append(j["average"])
                h_vals.append(sf.get("hallucination_score", 0.0) or 0.0)
        if len(f_vals) >= 5:
            rho_fj, _ = spearmanr(f_vals, j_vals)
            rho_fh, _ = spearmanr(f_vals, h_vals)
            per_condition[cond] = {
                "faith_vs_judge": round(float(rho_fj), 4),
                "faith_vs_halluc": round(float(rho_fh), 4),
                "count": len(f_vals),
            }

    output = {
        "run_id": make_run_id("step5_corr"),
        "overall": overall,
        "per_condition": per_condition,
        "sample_count": len(faithfulness_vals),
    }

    path = OUTPUT_DIR / "cross_correlation.json"
    save_json(output, path)
    logger.info("교차 상관 결과 저장: %s", path)
    return path


def _interpret_rho(rho: float) -> str:
    abs_rho = abs(rho)
    if abs_rho >= 0.9:
        return "very_strong (redundant)"
    if abs_rho >= 0.7:
        return "strong"
    if abs_rho >= 0.5:
        return "moderate (complementary)"
    if abs_rho >= 0.3:
        return "weak (complementary)"
    return "negligible (independent)"


def _analyze_detection_coverage(samples: list[dict]) -> Path:
    """추가 분석: 단독 vs 조합 평가 탐지율 비교."""
    logger.info("--- 탐지율 분석: 단독 vs 조합 ---")

    valid = []
    for s in samples:
        ev = s.get("eval", {})
        ragas = ev.get("ragas")
        judge = ev.get("judge")
        safety = ev.get("safety")
        if ragas and judge and safety:
            valid.append(s)

    logger.info("탐지율 분석 대상: %d건", len(valid))

    def _flag_ragas(s: dict) -> bool:
        f = s["eval"]["ragas"].get("faithfulness")
        return f is not None and f < FAITHFULNESS_THRESHOLD

    def _flag_judge(s: dict) -> bool:
        return s["eval"]["judge"].get("average", 5.0) < JUDGE_AVG_THRESHOLD

    def _flag_safety(s: dict) -> bool:
        h = s["eval"]["safety"].get("hallucination_score")
        return h is not None and h > HALLUCINATION_THRESHOLD

    detectors = {"ragas": _flag_ragas, "judge": _flag_judge, "safety": _flag_safety}

    flagged_sets: dict[str, set[int]] = {}
    for name, fn in detectors.items():
        flagged_sets[name] = {i for i, s in enumerate(valid) if fn(s)}

    total = len(valid)

    single_stage = {}
    for name, fset in flagged_sets.items():
        single_stage[f"{name}_only"] = {
            "flagged": len(fset),
            "rate": round(len(fset) / total, 4) if total > 0 else 0.0,
        }
        logger.info("  단독 %s: %d건 (%.1f%%)", name, len(fset), len(fset) / total * 100 if total else 0)

    stage_names = list(detectors.keys())
    two_stage = {}
    for a, b in combinations(stage_names, 2):
        union = flagged_sets[a] | flagged_sets[b]
        key = f"{a}+{b}"
        two_stage[key] = {
            "flagged": len(union),
            "rate": round(len(union) / total, 4) if total > 0 else 0.0,
        }
        logger.info("  2단계 %s: %d건 (%.1f%%)", key, len(union), len(union) / total * 100 if total else 0)

    all_union = flagged_sets["ragas"] | flagged_sets["judge"] | flagged_sets["safety"]
    three_stage = {
        "ragas+judge+safety": {
            "flagged": len(all_union),
            "rate": round(len(all_union) / total, 4) if total > 0 else 0.0,
        }
    }
    logger.info("  3단계 전체: %d건 (%.1f%%)", len(all_union), len(all_union) / total * 100 if total else 0)

    unique = {}
    for name in stage_names:
        others = set()
        for other_name in stage_names:
            if other_name != name:
                others |= flagged_sets[other_name]
        only_this = flagged_sets[name] - others
        unique[f"only_{name}_caught"] = {
            "count": len(only_this),
            "rate": round(len(only_this) / total, 4) if total > 0 else 0.0,
        }
        logger.info("  %s만 잡은 케이스: %d건", name, len(only_this))

    disagreement = {}
    for a, b in combinations(stage_names, 2):
        a_pass_b_fail = len(flagged_sets[b] - flagged_sets[a])
        b_pass_a_fail = len(flagged_sets[a] - flagged_sets[b])
        disagreement[f"{a}_pass_{b}_fail"] = {
            "count": a_pass_b_fail,
            "rate": round(a_pass_b_fail / total, 4) if total > 0 else 0.0,
        }
        disagreement[f"{b}_pass_{a}_fail"] = {
            "count": b_pass_a_fail,
            "rate": round(b_pass_a_fail / total, 4) if total > 0 else 0.0,
        }

    output = {
        "run_id": make_run_id("step5_detect"),
        "thresholds": {
            "ragas_faithfulness_lt": FAITHFULNESS_THRESHOLD,
            "judge_average_lt": JUDGE_AVG_THRESHOLD,
            "hallucination_gt": HALLUCINATION_THRESHOLD,
        },
        "total_samples": total,
        "single_stage": single_stage,
        "two_stage_union": two_stage,
        "three_stage_union": three_stage,
        "unique_detection": unique,
        "disagreement_matrix": disagreement,
    }

    path = OUTPUT_DIR / "detection_coverage.json"
    save_json(output, path)
    logger.info("탐지율 분석 결과 저장: %s", path)
    return path


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    main()
