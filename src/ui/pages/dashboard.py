"""평가 대시보드 페이지."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import streamlit as st

from src.ui.components.metrics_display import render_eval_summary, render_metrics_table

logger = logging.getLogger(__name__)

_RESULTS_DIR = Path("data/eval/results")


def _load_result_files() -> dict[str, list[dict[str, Any]]]:
    """data/eval/results/ 디렉토리의 JSON 파일 로드."""
    results: dict[str, list[dict[str, Any]]] = {}
    if not _RESULTS_DIR.exists():
        return results
    for fp in sorted(_RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, list):
                results[fp.stem] = data
            elif isinstance(data, dict) and "results" in data:
                results[fp.stem] = data["results"]
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load %s", fp)
    return results


def _show_average_chart(items: list[dict[str, Any]]) -> None:
    """평균 메트릭을 바 차트로 표시."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.caption("Plotly가 설치되지 않아 차트를 표시할 수 없습니다.")
        return

    ragas_sums: dict[str, float] = {}
    ragas_counts: dict[str, int] = {}
    judge_sums: dict[str, float] = {}
    judge_counts: dict[str, int] = {}

    for item in items:
        ragas = item.get("ragas") or {}
        for k, v in ragas.items():
            if v is not None:
                ragas_sums[k] = ragas_sums.get(k, 0) + v
                ragas_counts[k] = ragas_counts.get(k, 0) + 1
        judge = item.get("judge") or {}
        for k, v in judge.items():
            if v is not None:
                judge_sums[k] = judge_sums.get(k, 0) + v
                judge_counts[k] = judge_counts.get(k, 0) + 1

    if not ragas_sums and not judge_sums:
        return

    fig = go.Figure()

    if ragas_sums:
        labels = list(ragas_sums.keys())
        avgs = [ragas_sums[k] / ragas_counts[k] for k in labels]
        fig.add_trace(
            go.Bar(
                name="RAGAS",
                x=labels,
                y=avgs,
                marker_color="#5E6AD2",
                marker_line_width=0,
            )
        )

    if judge_sums:
        labels = list(judge_sums.keys())
        avgs = [judge_sums[k] / judge_counts[k] for k in labels]
        fig.add_trace(
            go.Bar(
                name="LLM Judge",
                x=labels,
                y=avgs,
                marker_color="#6C72CB",
                marker_line_width=0,
            )
        )

    fig.update_layout(
        title=dict(text="평균 메트릭 점수", font=dict(size=14, family="Inter", color="#0A0A0B")),
        yaxis_title="점수",
        barmode="group",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#3B3F46", size=12),
        height=380,
        margin=dict(t=50, b=40, l=50, r=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
    )
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.04)", gridwidth=0.5)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0.04)", gridwidth=0.5, range=[0, 1])

    st.plotly_chart(fig, use_container_width=True)


# ── 페이지 렌더링 ──────────────────────────────────

st.markdown(
    """<div class="page-header">
        <h1>평가 대시보드</h1>
        <p>RAG 파이프라인의 3단계 평가 결과를 분석합니다.</p>
    </div>""",
    unsafe_allow_html=True,
)

uploaded = st.file_uploader("평가 결과 JSON 파일 업로드", type=["json"])
uploaded_results: list[dict[str, Any]] | None = None
if uploaded is not None:
    try:
        raw = json.loads(uploaded.read())
        if isinstance(raw, list):
            uploaded_results = raw
        elif isinstance(raw, dict) and "results" in raw:
            uploaded_results = raw["results"]
        else:
            st.error("지원하지 않는 JSON 형식입니다.")
    except json.JSONDecodeError:
        st.error("잘못된 JSON 파일입니다.")

all_results = _load_result_files()

if uploaded_results:
    all_results["(업로드됨)"] = uploaded_results

if not all_results:
    st.markdown(
        '<div class="info-banner">'
        "평가 결과가 없습니다. <code>data/eval/results/</code> 디렉토리에 JSON 파일을 추가하거나 위에서 업로드하세요."
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

result_names = list(all_results.keys())
selected_name = st.selectbox("평가 결과 선택", result_names)

if selected_name:
    items = all_results[selected_name]

    total = len(items)
    errors = sum(1 for it in items if it.get("error"))
    st.markdown(f"**{selected_name}** — {total}건 중 {total - errors}건 평가 완료")

    if items:
        st.markdown('<div class="section-label">전체 결과</div>', unsafe_allow_html=True)
        render_metrics_table(items)

        st.markdown('<div class="section-label">개별 상세</div>', unsafe_allow_html=True)
        for item in items:
            item_id = item.get("id", "unknown")
            with st.expander(f"Sample: {item_id}"):
                render_eval_summary(item)

        st.markdown('<div class="section-label">평균 메트릭 차트</div>', unsafe_allow_html=True)
        _show_average_chart(items)
