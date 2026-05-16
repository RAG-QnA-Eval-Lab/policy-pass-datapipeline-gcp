"""논문 표 6~10 + 그림 1~5 생성 — step1~step5 결과 JSON에서 논문용 테이블·차트 자동 생성.

LLM 호출 없음 — 순수 통계 집계 + Plotly/matplotlib 시각화.

사용법:
    python -m scripts.experiments.step6_tables_figures
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from scripts.experiments._common import (
    BASE_OUTPUT_DIR,
    load_json,
    make_run_id,
    save_json,
    setup_logging,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = BASE_OUTPUT_DIR / "step6_tables_figures"


def main() -> Path:
    setup_logging("step6_tables_figures", OUTPUT_DIR)
    logger.info("=== 논문 표·그림 생성 시작 ===")

    tables: dict[str, dict | list] = {}

    tables["table6"] = _build_table6_retrieval()
    t7, t8, t9 = _build_tables7_8_9_generation()
    tables["table7_ragas"] = t7
    tables["table8_judge"] = t8
    tables["table9_safety"] = t9
    tables["table10_judge_cost"] = _build_table10_judge_cost()
    tables["table_bias"] = _build_table_bias()
    tables["table_detection"] = _build_table_detection()
    tables["table_correlation"] = _build_table_correlation()

    figures_dir = OUTPUT_DIR / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    _generate_figures(tables, figures_dir)

    output = {
        "run_id": make_run_id("step6"),
        "tables": tables,
        "figures_dir": str(figures_dir),
    }

    output_path = OUTPUT_DIR / "tables_figures.json"
    save_json(output, output_path)
    logger.info("=== 논문 표·그림 생성 완료: %s ===", output_path)
    return output_path


def _build_table6_retrieval() -> list[dict]:
    """표 6: 검색 전략별 성능 비교."""
    path = BASE_OUTPUT_DIR / "step1_retrieval" / "retrieval_results.json"
    if not path.exists():
        logger.warning("step1 결과 없음 — 표 6 건너뜀")
        return []

    data = load_json(path)
    results = data.get("results", {})

    rows = []
    for strategy, samples in results.items():
        cp_vals = [s["context_precision"] for s in samples if s.get("context_precision") is not None]
        cr_vals = [s["context_recall"] for s in samples if s.get("context_recall") is not None]
        lat_vals = [s["retrieval_latency"] for s in samples if s.get("retrieval_latency") is not None]

        rows.append(
            {
                "strategy": strategy,
                "context_precision_mean": round(float(np.mean(cp_vals)), 4) if cp_vals else None,
                "context_precision_std": round(float(np.std(cp_vals)), 4) if cp_vals else None,
                "context_recall_mean": round(float(np.mean(cr_vals)), 4) if cr_vals else None,
                "context_recall_std": round(float(np.std(cr_vals)), 4) if cr_vals else None,
                "latency_mean": round(float(np.mean(lat_vals)), 4) if lat_vals else None,
                "sample_count": len(samples),
            }
        )

    logger.info("표 6: %d개 전략 집계", len(rows))
    return rows


def _build_tables7_8_9_generation() -> tuple[list[dict], list[dict], list[dict]]:
    """표 7 (RAGAS), 표 8 (Judge), 표 9 (Safety): 멀티 LLM 응답 품질."""
    path = BASE_OUTPUT_DIR / "step3_evaluation" / "eval_gpt4o_mini_judge.json"
    if not path.exists():
        logger.warning("step3 결과 없음 — 표 7/8/9 건너뜀")
        return [], [], []

    data = load_json(path)
    results = data.get("results", [])

    by_condition: dict[str, list[dict]] = {}
    for s in results:
        cond = s.get("condition", "unknown")
        by_condition.setdefault(cond, []).append(s)

    ragas_rows = []
    judge_rows = []
    safety_rows = []

    for cond, samples in sorted(by_condition.items()):
        valid_ragas = [s for s in samples if (s.get("eval") or {}).get("ragas")]
        valid_judge = [s for s in samples if (s.get("eval") or {}).get("judge")]
        valid_safety = [s for s in samples if (s.get("eval") or {}).get("safety")]

        if valid_ragas:
            ragas_metrics = {}
            for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                vals = [s["eval"]["ragas"][key] for s in valid_ragas if s["eval"]["ragas"].get(key) is not None]
                ragas_metrics[f"{key}_mean"] = round(float(np.mean(vals)), 4) if vals else None
                ragas_metrics[f"{key}_std"] = round(float(np.std(vals)), 4) if vals else None
            ragas_rows.append({"condition": cond, "count": len(valid_ragas), **ragas_metrics})

        if valid_judge:
            judge_metrics = {}
            for key in ["citation_accuracy", "completeness", "readability", "average"]:
                vals = [s["eval"]["judge"][key] for s in valid_judge if s["eval"]["judge"].get(key) is not None]
                judge_metrics[f"{key}_mean"] = round(float(np.mean(vals)), 4) if vals else None
                judge_metrics[f"{key}_std"] = round(float(np.std(vals)), 4) if vals else None
            judge_rows.append({"condition": cond, "count": len(valid_judge), **judge_metrics})

        if valid_safety:
            h_vals = [
                s["eval"]["safety"]["hallucination_score"]
                for s in valid_safety
                if s["eval"]["safety"].get("hallucination_score") is not None
            ]
            safety_rows.append(
                {
                    "condition": cond,
                    "count": len(valid_safety),
                    "hallucination_mean": round(float(np.mean(h_vals)), 4) if h_vals else None,
                    "hallucination_std": round(float(np.std(h_vals)), 4) if h_vals else None,
                }
            )

    logger.info("표 7: %d조건, 표 8: %d조건, 표 9: %d조건", len(ragas_rows), len(judge_rows), len(safety_rows))
    return ragas_rows, judge_rows, safety_rows


def _build_table10_judge_cost() -> dict:
    """표 10: Judge 모델 비용-성능 비교."""
    path = BASE_OUTPUT_DIR / "step4_judge_comparison" / "judge_comparison.json"
    if not path.exists():
        logger.warning("step4 결과 없음 — 표 10 건너뜀")
        return {}

    data = load_json(path)

    agreement = data.get("agreement_metrics", {})
    cost = data.get("cost_comparison", {})

    avg_metrics = agreement.get("average", {})

    table = {
        "kendall_tau": avg_metrics.get("kendall_tau"),
        "spearman_rho": avg_metrics.get("spearman_rho"),
        "mae": avg_metrics.get("mae"),
        "perfect_agreement_rate": avg_metrics.get("perfect_agreement_rate"),
        "class_agreement_rate": avg_metrics.get("class_agreement_rate"),
        "cost_gpt4o_mini_usd": cost.get("gpt-4o-mini", {}).get("estimated_usd"),
        "cost_gemini_pro_usd": cost.get("gemini-3.1-pro", {}).get("estimated_usd"),
        "cost_ratio": cost.get("cost_ratio"),
        "per_metric": {
            metric: {
                "kendall_tau": vals.get("kendall_tau"),
                "mae": vals.get("mae"),
                "class_agreement": vals.get("class_agreement_rate"),
            }
            for metric, vals in agreement.items()
        },
    }

    logger.info(
        "표 10: τ=%s, MAE=%s, 비용비=%s",
        avg_metrics.get("kendall_tau"),
        avg_metrics.get("mae"),
        cost.get("cost_ratio"),
    )
    return table


def _build_table_bias() -> dict:
    """Position Bias 분석 결과 요약."""
    path = BASE_OUTPUT_DIR / "step5_analysis" / "position_bias.json"
    if not path.exists():
        logger.warning("step5 bias 결과 없음 — 건너뜀")
        return {}

    data = load_json(path)
    return {
        "per_metric_delta": data.get("per_metric_delta", {}),
        "variance_comparison": data.get("variance_comparison", {}),
        "total_samples": data.get("total_samples", 0),
    }


def _build_table_detection() -> dict:
    """탐지율 분석 결과 요약."""
    path = BASE_OUTPUT_DIR / "step5_analysis" / "detection_coverage.json"
    if not path.exists():
        logger.warning("step5 detection 결과 없음 — 건너뜀")
        return {}

    data = load_json(path)
    return {
        "thresholds": data.get("thresholds", {}),
        "single_stage": data.get("single_stage", {}),
        "two_stage_union": data.get("two_stage_union", {}),
        "three_stage_union": data.get("three_stage_union", {}),
        "unique_detection": data.get("unique_detection", {}),
        "total_samples": data.get("total_samples", 0),
    }


def _build_table_correlation() -> dict:
    """교차 상관 분석 결과 요약."""
    path = BASE_OUTPUT_DIR / "step5_analysis" / "cross_correlation.json"
    if not path.exists():
        logger.warning("step5 correlation 결과 없음 — 건너뜀")
        return {}

    data = load_json(path)
    return {
        "overall": data.get("overall", {}),
        "per_condition": data.get("per_condition", {}),
        "sample_count": data.get("sample_count", 0),
    }


def _generate_figures(tables: dict, figures_dir: Path) -> None:
    """Plotly 차트 생성 — plotly 없으면 건너뜀."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        logger.warning("plotly 미설치 — 그림 생성 건너뜀 (pip install plotly kaleido)")
        return

    _fig_radar_ragas(tables.get("table7_ragas", []), figures_dir, go)
    _fig_judge_heatmap(tables.get("table8_judge", []), figures_dir, go)
    _fig_detection_bar(tables.get("table_detection", {}), figures_dir, go)
    _fig_bias_histogram(tables.get("table_bias", {}), figures_dir, go)
    _fig_cost_scatter(tables.get("table10_judge_cost", {}), figures_dir, go, make_subplots)


def _fig_radar_ragas(ragas_rows: list[dict], figures_dir: Path, go: object) -> None:
    """그림 4: 모델별 RAGAS 지표 레이더 차트."""
    if not ragas_rows:
        return

    categories = ["Faithfulness", "Answer Relevancy", "Context Precision", "Context Recall"]
    cat_keys = ["faithfulness_mean", "answer_relevancy_mean", "context_precision_mean", "context_recall_mean"]

    fig = go.Figure()

    for row in ragas_rows:
        values = [row.get(k, 0) or 0 for k in cat_keys]
        values.append(values[0])
        fig.add_trace(
            go.Scatterpolar(
                r=values,
                theta=categories + [categories[0]],
                fill="toself",
                name=row["condition"],
                opacity=0.7,
            )
        )

    fig.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 1]}},
        title="모델별 RAGAS 지표 비교",
        showlegend=True,
    )

    path = figures_dir / "fig4_ragas_radar.html"
    fig.write_html(str(path))
    logger.info("그림 4 저장: %s", path)

    try:
        png_path = figures_dir / "fig4_ragas_radar.png"
        fig.write_image(str(png_path), width=800, height=600)
    except Exception:
        logger.debug("PNG 저장 실패 (kaleido 필요)")


def _fig_judge_heatmap(judge_rows: list[dict], figures_dir: Path, go: object) -> None:
    """그림: 모델별 Judge 점수 히트맵."""
    if not judge_rows:
        return

    metrics = ["citation_accuracy_mean", "completeness_mean", "readability_mean", "average_mean"]
    labels = ["Citation Accuracy", "Completeness", "Readability", "Average"]

    z = []
    y_labels = []
    for row in judge_rows:
        z.append([row.get(m, 0) or 0 for m in metrics])
        y_labels.append(row["condition"])

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=labels,
            y=y_labels,
            colorscale="RdYlGn",
            zmin=1,
            zmax=5,
            text=[[f"{v:.2f}" for v in row] for row in z],
            texttemplate="%{text}",
        )
    )

    fig.update_layout(title="모델별 Judge 점수 히트맵", height=max(400, len(y_labels) * 50))

    path = figures_dir / "fig_judge_heatmap.html"
    fig.write_html(str(path))
    logger.info("Judge 히트맵 저장: %s", path)


def _fig_detection_bar(detection: dict, figures_dir: Path, go: object) -> None:
    """탐지율 비교 막대 차트: 단독 vs 2단계 vs 3단계."""
    if not detection:
        return

    categories = []
    rates = []

    for name, val in detection.get("single_stage", {}).items():
        categories.append(name.replace("_only", ""))
        rates.append(val.get("rate", 0) * 100)

    for name, val in detection.get("two_stage_union", {}).items():
        categories.append(name)
        rates.append(val.get("rate", 0) * 100)

    for name, val in detection.get("three_stage_union", {}).items():
        categories.append(name)
        rates.append(val.get("rate", 0) * 100)

    colors = (
        ["#4C78A8"] * len(detection.get("single_stage", {}))
        + ["#F58518"] * len(detection.get("two_stage_union", {}))
        + ["#E45756"] * len(detection.get("three_stage_union", {}))
    )

    fig = go.Figure(
        data=go.Bar(
            x=categories,
            y=rates,
            marker_color=colors,
            text=[f"{r:.1f}%" for r in rates],
            textposition="auto",
        )
    )

    fig.update_layout(
        title="평가 단계별 문제 탐지율 비교",
        xaxis_title="평가 조합",
        yaxis_title="탐지율 (%)",
        yaxis_range=[0, 100],
    )

    path = figures_dir / "fig_detection_coverage.html"
    fig.write_html(str(path))
    logger.info("탐지율 차트 저장: %s", path)


def _fig_bias_histogram(bias: dict, figures_dir: Path, go: object) -> None:
    """그림 5: Position Bias 점수 차이 분포."""
    per_metric = bias.get("per_metric_delta", {})
    if not per_metric:
        return

    fig = go.Figure()

    for metric, info in per_metric.items():
        delta_dist = info.get("delta_distribution", {})
        if not delta_dist:
            continue
        x_vals = sorted(delta_dist.keys(), key=lambda v: float(v))
        y_vals = [delta_dist[k] for k in x_vals]
        fig.add_trace(
            go.Bar(
                x=[f"Δ={v}" for v in x_vals],
                y=y_vals,
                name=metric,
            )
        )

    fig.update_layout(
        title="Position Bias: 원본-셔플 점수 차이 분포",
        xaxis_title="점수 차이 (|원본 - 셔플|)",
        yaxis_title="빈도",
        barmode="group",
    )

    path = figures_dir / "fig5_bias_histogram.html"
    fig.write_html(str(path))
    logger.info("그림 5 저장: %s", path)


def _fig_cost_scatter(cost_table: dict, figures_dir: Path, go: object, make_subplots: object) -> None:
    """비용-성능 산점도."""
    if not cost_table or not cost_table.get("per_metric"):
        return

    per_metric = cost_table["per_metric"]
    metrics = [m for m in per_metric if m != "average"]

    if not metrics:
        return

    fig = go.Figure()

    for metric in metrics:
        info = per_metric[metric]
        tau = info.get("kendall_tau")
        mae = info.get("mae")
        if tau is not None and mae is not None:
            fig.add_trace(
                go.Scatter(
                    x=[mae],
                    y=[tau],
                    mode="markers+text",
                    text=[metric],
                    textposition="top center",
                    name=metric,
                    marker={"size": 12},
                )
            )

    fig.update_layout(
        title="GPT-4o-mini vs Gemini 3.1 Pro: 메트릭별 일치도",
        xaxis_title="MAE (낮을수록 좋음)",
        yaxis_title="Kendall τ (높을수록 좋음)",
        yaxis_range=[0, 1],
    )

    path = figures_dir / "fig_cost_performance.html"
    fig.write_html(str(path))
    logger.info("비용-성능 차트 저장: %s", path)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    main()
