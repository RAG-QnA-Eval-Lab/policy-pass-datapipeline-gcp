"""정책 QnA 챗봇 페이지."""

from __future__ import annotations

import streamlit as st

from src.ui.components.chat_message import render_answer
from src.ui.utils.api_client import get_api_client
from src.ui.utils.session_state import (
    KEY_MESSAGES,
    KEY_MODEL,
    KEY_NO_RAG,
    KEY_STRATEGY,
    KEY_TEMPERATURE,
    KEY_TOP_K,
)

EXAMPLE_QUESTIONS = [
    ("청년 월세 지원 정책에 대해 알려주세요", "주거"),
    ("취업 준비생을 위한 정부 지원은?", "취업"),
    ("대학생이 받을 수 있는 장학금 정책은?", "교육"),
    ("청년 전세자금 대출 조건이 어떻게 되나요?", "금융"),
]

STRATEGY_OPTIONS = {
    "hybrid": "하이브리드 (권장)",
    "hybrid_rerank": "하이브리드 + 리랭크",
    "vector_only": "벡터 검색",
    "bm25_only": "BM25 키워드 검색",
}

# ── 사이드바: 설정 ──────────────────────────────────

client = get_api_client()

with st.sidebar:
    st.markdown("### 모델 설정")

    models_data = client.get_models()
    model_keys: list[str] = []
    model_descriptions: dict[str, str] = {}
    default_model = ""
    if models_data:
        for m in models_data.get("models", []):
            model_keys.append(m["key"])
            model_descriptions[m["key"]] = m.get("description", m["key"])
        default_model = models_data.get("default_model", "")

    if model_keys:
        default_idx = 0
        if st.session_state[KEY_MODEL] in model_keys:
            default_idx = model_keys.index(st.session_state[KEY_MODEL])
        elif default_model in model_keys:
            default_idx = model_keys.index(default_model)
        selected = st.selectbox(
            "모델",
            model_keys,
            index=default_idx,
            format_func=lambda k: model_descriptions.get(k, k),
        )
        st.session_state[KEY_MODEL] = selected
    else:
        st.warning("모델 목록을 불러올 수 없습니다")

    st.markdown("### 검색 설정")

    strategy_keys = list(STRATEGY_OPTIONS.keys())
    current_strategy = st.session_state[KEY_STRATEGY]
    strategy_idx = strategy_keys.index(current_strategy) if current_strategy in strategy_keys else 0
    st.session_state[KEY_STRATEGY] = st.selectbox(
        "검색 전략",
        strategy_keys,
        index=strategy_idx,
        format_func=lambda k: STRATEGY_OPTIONS[k],
    )

    st.session_state[KEY_TOP_K] = st.slider("검색 결과 수 (top_k)", 1, 20, st.session_state[KEY_TOP_K])
    st.session_state[KEY_TEMPERATURE] = st.slider("Temperature", 0.0, 2.0, st.session_state[KEY_TEMPERATURE], step=0.1)
    st.session_state[KEY_NO_RAG] = st.toggle("RAG 없이 답변", value=st.session_state[KEY_NO_RAG])

    if st.button("대화 초기화", use_container_width=True):
        st.session_state[KEY_MESSAGES] = []
        st.rerun()

# ── 메인 영역 ───────────────────────────────────────

messages: list[dict] = st.session_state[KEY_MESSAGES]

if not messages:
    st.markdown(
        """<div class="page-header">
            <h1>청년 정책 QnA</h1>
            <p>궁금한 청년 정책에 대해 질문해보세요. AI가 관련 정책을 검색하고 답변합니다.</p>
        </div>""",
        unsafe_allow_html=True,
    )

    cols = st.columns(2, gap="medium")
    for i, (q, tag) in enumerate(EXAMPLE_QUESTIONS):
        if cols[i % 2].button(f"{tag}  |  {q}", key=f"example_{i}", use_container_width=True):
            messages.append({"role": "user", "content": q})
            st.rerun()
else:
    col1, col2 = st.columns([6, 1])
    col1.markdown("#### 정책 QnA")
    if col2.button("새 대화", use_container_width=True):
        st.session_state[KEY_MESSAGES] = []
        st.rerun()

for msg in messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and "response_data" in msg:
            render_answer(msg["response_data"])
        else:
            st.markdown(msg["content"])

pending_query: str | None = None

if messages and messages[-1]["role"] == "user" and (len(messages) < 2 or messages[-2]["role"] != "assistant"):
    pending_query = messages[-1]["content"]

user_input = st.chat_input("정책에 대해 질문하세요...")

if user_input:
    messages.append({"role": "user", "content": user_input})
    pending_query = user_input

    with st.chat_message("user"):
        st.markdown(user_input)

if pending_query:
    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            resp = client.generate(
                query=pending_query,
                model=st.session_state[KEY_MODEL],
                strategy=st.session_state[KEY_STRATEGY],
                top_k=st.session_state[KEY_TOP_K],
                temperature=st.session_state[KEY_TEMPERATURE],
                no_rag=st.session_state[KEY_NO_RAG],
            )
            if resp:
                render_answer(resp)
                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.get("answer", ""),
                        "response_data": resp,
                    }
                )
            else:
                st.error("답변 생성에 실패했습니다. API 서버를 확인하세요.")
                messages.append({"role": "assistant", "content": "답변 생성에 실패했습니다."})
