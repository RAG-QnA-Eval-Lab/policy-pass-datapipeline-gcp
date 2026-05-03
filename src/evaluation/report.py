"""평가 리포트 생성 — JSON 저장 + 콘솔 요약."""

from __future__ import annotations

import html as _html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_report(
    results: dict,
    output_dir: Path,
    run_id: str = "",
    metadata: dict | None = None,
) -> Path:
    """평가 결과를 JSON 리포트로 저장하고 콘솔 요약을 출력한다.

    Args:
        results: 모델별 평가 결과 dict.
            { "model_key": [ { ...sample, "eval_result": {...} }, ... ], ... }
        output_dir: 리포트 저장 디렉토리.
        run_id: 실행 ID (파일명에 사용).
        metadata: strategy, models 등 실행 메타데이터.

    Returns:
        저장된 리포트 파일 경로.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"report_{run_id}_{timestamp}.json" if run_id else f"report_{timestamp}.json"
    output_path = output_dir / filename

    summary = _build_summary(results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "metadata": metadata or {},
        "summary": summary,
        "details": results,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    html_path = output_path.with_suffix(".html")
    html_path.write_text(_build_html_report(report), encoding="utf-8")

    _print_console_summary(summary)
    logger.info("리포트 저장: %s, %s", output_path, html_path)
    return output_path


def _build_summary(results: dict) -> dict:
    """모델별 평균 점수 요약."""
    summary: dict[str, dict] = {}

    for model_key, samples in results.items():
        ragas_scores: dict[str, list[float]] = {
            "faithfulness": [],
            "answer_relevancy": [],
            "context_precision": [],
            "context_recall": [],
        }
        judge_scores: dict[str, list[float]] = {
            "citation_accuracy": [],
            "completeness": [],
            "readability": [],
            "average": [],
        }
        safety_scores: list[float] = []
        latencies: list[float] = []
        error_count = 0

        for sample in samples:
            eval_result = sample.get("eval_result")
            if eval_result is None:
                error_count += 1
                continue

            ragas = eval_result.get("ragas")
            if ragas:
                for key in ragas_scores:
                    val = ragas.get(key)
                    if val is not None:
                        ragas_scores[key].append(val)

            judge = eval_result.get("judge")
            if judge:
                for key in judge_scores:
                    val = judge.get(key)
                    if val is not None:
                        judge_scores[key].append(val)

            safety = eval_result.get("safety")
            if safety:
                val = safety.get("hallucination_score")
                if val is not None:
                    safety_scores.append(val)

            latencies.append(eval_result.get("latency", 0.0))

        summary[model_key] = {
            "total_samples": len(samples),
            "errors": error_count,
            "ragas_avg": {k: _safe_mean(v) for k, v in ragas_scores.items()},
            "judge_avg": {k: _safe_mean(v) for k, v in judge_scores.items()},
            "safety_avg_hallucination": _safe_mean(safety_scores),
            "avg_latency": _safe_mean(latencies),
        }

    return summary


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _print_console_summary(summary: dict) -> None:
    """콘솔에 모델별 요약 테이블 출력."""
    cols = [
        f"{'Model':<20}",
        f"{'Faith':>7} {'Relev':>7} {'Prec':>7} {'Recall':>7}",
        f"{'Cite':>5} {'Comp':>5} {'Read':>5} {'Avg':>5}",
        f"{'Halluc':>7} {'Lat(s)':>7}",
    ]
    header = " | ".join(cols)
    sep = "-" * len(header)

    print("\n" + sep)
    print("                     RAGAS (0-1)                    | Judge (1-5)           | Safety")
    print(header)
    print(sep)

    for model, data in summary.items():
        ragas = data.get("ragas_avg", {})
        judge = data.get("judge_avg", {})
        halluc = data.get("safety_avg_hallucination")
        lat = data.get("avg_latency")

        row = (
            f"{model:<20} "
            f"{_fmt(ragas.get('faithfulness')):>7} "
            f"{_fmt(ragas.get('answer_relevancy')):>7} "
            f"{_fmt(ragas.get('context_precision')):>7} "
            f"{_fmt(ragas.get('context_recall')):>7} | "
            f"{_fmt(judge.get('citation_accuracy')):>5} "
            f"{_fmt(judge.get('completeness')):>5} "
            f"{_fmt(judge.get('readability')):>5} "
            f"{_fmt(judge.get('average')):>5} | "
            f"{_fmt(halluc):>7} "
            f"{_fmt(lat):>7}"
        )
        print(row)

    print(sep + "\n")


def _fmt(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.3f}"


def _build_html_report(report: dict) -> str:
    metadata = report.get("metadata", {})
    summary = report.get("summary", {})

    rows = []
    for model, data in summary.items():
        ragas = data.get("ragas_avg", {})
        judge = data.get("judge_avg", {})
        rows.append(
            "<tr>"
            f"<td>{_html.escape(model)}</td>"
            f"<td>{_fmt(ragas.get('faithfulness'))}</td>"
            f"<td>{_fmt(ragas.get('answer_relevancy'))}</td>"
            f"<td>{_fmt(ragas.get('context_precision'))}</td>"
            f"<td>{_fmt(ragas.get('context_recall'))}</td>"
            f"<td>{_fmt(judge.get('citation_accuracy'))}</td>"
            f"<td>{_fmt(judge.get('completeness'))}</td>"
            f"<td>{_fmt(judge.get('readability'))}</td>"
            f"<td>{_fmt(judge.get('average'))}</td>"
            f"<td>{_fmt(data.get('safety_avg_hallucination'))}</td>"
            f"<td>{_fmt(data.get('avg_latency'))}</td>"
            f"<td>{data.get('errors', 0)}</td>"
            "</tr>"
        )

    strategy = _html.escape(metadata.get("strategy", ""))
    models = _html.escape(", ".join(metadata.get("models", [])))

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>RAG Evaluation Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2937; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .meta {{ margin-bottom: 24px; color: #4b5563; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 10px 12px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #f3f4f6; }}
    tr:nth-child(even) {{ background: #f9fafb; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>RAG Evaluation Report</h1>
  <div class="meta">
    <div><strong>Run ID:</strong> <code>{_html.escape(report.get("run_id", ""))}</code></div>
    <div><strong>Generated At:</strong> {_html.escape(report.get("generated_at", ""))}</div>
    <div><strong>Strategy:</strong> {strategy or "N/A"}</div>
    <div><strong>Models:</strong> {models or "N/A"}</div>
  </div>

  <h2>Summary</h2>
  <table>
    <thead>
      <tr>
        <th>Model</th>
        <th>Faithfulness</th>
        <th>Answer Relevancy</th>
        <th>Context Precision</th>
        <th>Context Recall</th>
        <th>Citation</th>
        <th>Completeness</th>
        <th>Readability</th>
        <th>Judge Avg</th>
        <th>Hallucination</th>
        <th>Latency</th>
        <th>Errors</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
