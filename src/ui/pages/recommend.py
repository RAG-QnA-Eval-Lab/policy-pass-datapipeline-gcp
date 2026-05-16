"""맞춤 추천 페이지."""

from __future__ import annotations

import streamlit as st

from src.ui.components.chat_message import render_answer
from src.ui.utils.api_client import get_api_client

REGIONS = [
    "전국",
    "서울",
    "경기",
    "인천",
    "부산",
    "대구",
    "대전",
    "광주",
    "울산",
    "세종",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
]

INTEREST_AREAS = ["주거", "취업", "창업", "교육", "복지", "금융"]

st.markdown(
    """<div class="page-header">
        <h1>맞춤 정책 추천</h1>
        <p>나의 상황을 입력하면 AI가 맞춤 정책을 찾아 추천합니다.</p>
    </div>""",
    unsafe_allow_html=True,
)

client = get_api_client()

with st.form("recommend_form"):
    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown('<div class="section-label">기본 정보</div>', unsafe_allow_html=True)
        age = st.number_input("나이", min_value=15, max_value=45, value=25)
        region = st.selectbox("거주 지역", REGIONS)
        income = st.selectbox(
            "소득 수준",
            [
                "선택 안 함",
                "기초생활수급",
                "차상위계층",
                "중위소득 50% 이하",
                "중위소득 100% 이하",
                "중위소득 100% 초과",
            ],
        )

    with col2:
        st.markdown('<div class="section-label">현재 상태</div>', unsafe_allow_html=True)
        employment = st.selectbox(
            "취업 상태",
            ["선택 안 함", "재학생", "졸업예정자", "미취업", "재직자", "자영업"],
        )
        interests = st.multiselect("관심 분야 (복수 선택)", INTEREST_AREAS, default=["주거", "취업"])

    submitted = st.form_submit_button("맞춤 정책 추천받기", use_container_width=True, type="primary")

if submitted:
    parts: list[str] = [f"나이 {age}세"]
    if region != "전국":
        parts.append(f"{region} 거주")
    if income != "선택 안 함":
        parts.append(f"소득 수준: {income}")
    if employment != "선택 안 함":
        parts.append(f"현재 상태: {employment}")
    if interests:
        parts.append(f"관심 분야: {', '.join(interests)}")

    profile = ", ".join(parts)
    query = (
        f"저는 {profile}인 청년입니다. "
        "저에게 맞는 정부 지원 정책을 추천해주세요. 각 정책의 자격 요건과 혜택을 알려주세요."
    )

    with st.spinner("맞춤 정책을 찾고 있습니다..."):
        resp = client.generate(query=query, strategy="hybrid", top_k=10)

    if resp:
        st.markdown('<div class="section-label">추천 결과</div>', unsafe_allow_html=True)
        render_answer(resp)
    else:
        st.error("추천 결과를 생성할 수 없습니다. API 서버를 확인하세요.")
