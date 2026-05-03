"""챗봇 메시지 컴포넌트."""

from __future__ import annotations

import html as _html
from typing import Any

import streamlit as st


def render_answer(response: dict[str, Any]) -> None:
    """생성 응답을 렌더링: 답변 + 출처 + 메트릭."""
    st.markdown(response.get("answer", ""))

    sources: list[dict[str, Any]] = response.get("sources", [])
    if sources:
        with st.expander(f"참고 출처 ({len(sources)}건)", expanded=False):
            for i, src in enumerate(sources, 1):
                title = _html.escape(src.get("title", "제목 없음"))
                source_name = _html.escape(src.get("source_name", ""))
                score = src.get("score", 0.0)
                content = src.get("content", "")
                preview = _html.escape(content[:150] + "..." if len(content) > 150 else content)
                header = f"{title}"
                if source_name:
                    header += f" &middot; {source_name}"
                st.markdown(
                    f"""<div class="source-card">
                        <div class="source-header">[{i}] {header}
                            <span class="source-score">{score:.2f}</span>
                        </div>
                        <div class="source-preview">{preview}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

    _render_response_meta(response)


def _render_response_meta(response: dict[str, Any]) -> None:
    token_usage = response.get("token_usage", {})
    total_tokens = token_usage.get("total_tokens", 0)
    total_ms = response.get("total_latency_ms", 0)
    model = response.get("model", "")
    strategy = response.get("strategy", "")

    chips: list[str] = []
    if model:
        short_model = model.split("/")[-1] if "/" in model else model
        chips.append(f'<span class="meta-chip">{_html.escape(short_model)}</span>')
    if strategy:
        chips.append(f'<span class="meta-chip">{_html.escape(strategy)}</span>')
    if total_tokens:
        chips.append(f'<span class="meta-chip">{total_tokens:,} tokens</span>')
    if total_ms:
        chips.append(f'<span class="meta-chip">{total_ms:.0f}ms</span>')

    if chips:
        st.markdown(f'<div class="response-meta">{"".join(chips)}</div>', unsafe_allow_html=True)
