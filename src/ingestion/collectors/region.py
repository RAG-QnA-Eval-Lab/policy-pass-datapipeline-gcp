"""지역 코드 ↔ 한국어 이름 변환 — 단일 소스."""

from __future__ import annotations

REGION_CODE_MAP: dict[str, str] = {
    "11": "서울",
    "26": "부산",
    "27": "대구",
    "28": "인천",
    "29": "광주",
    "30": "대전",
    "31": "울산",
    "36": "세종",
    "41": "경기",
    "42": "강원",
    "43": "충북",
    "44": "충남",
    "45": "전북",
    "46": "전남",
    "47": "경북",
    "48": "경남",
    "50": "제주",
    "51": "강원",
    "52": "전북",
}

# 19개 코드 → 17개 고유 이름 (강원 51/42, 전북 52/45 레거시 별칭).
_NATIONWIDE_THRESHOLD = 15


def format_region(raw: str) -> str:
    """지역 코드 문자열을 한국어 이름으로 변환.

    '11,26' → '부산, 서울'
    '전국'  → '전국'
    15개 이상 지역 → '전국'
    """
    if not raw or raw == "전국":
        return "전국"
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    names = sorted({REGION_CODE_MAP.get(c[:2], "") for c in codes} - {""})
    if not names or len(names) >= _NATIONWIDE_THRESHOLD:
        return "전국"
    return ", ".join(names)
