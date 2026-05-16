"""공공데이터포털 청년정책 API 수집기.

엔드포인트: https://www.youthcenter.go.kr/go/ythip/getPlcy
인증: apiKeyNm 쿼리 파라미터
서비스: 15143273 (LINK 타입, rtnType=json 필수)
"""

from __future__ import annotations

import logging
import time

import httpx

from config.settings import settings
from src.ingestion.collectors.base import (
    BaseCollector,
    Policy,
    normalize_category,
    parse_age,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
REQUEST_INTERVAL = 2.0


class DataPortalCollector(BaseCollector):
    """공공데이터포털 (온통청년 Open API 경유) 수집기."""

    source_name = "data_portal"

    def __init__(self, api_key: str | None = None, page_size: int = 100) -> None:
        self.api_key = api_key or settings.data_portal_api_key
        if not self.api_key:
            raise ValueError("DATA_PORTAL_API_KEY 환경변수가 설정되어 있지 않습니다.")
        self.page_size = page_size

    def collect(self, max_items: int | None = None) -> list[Policy]:
        policies: list[Policy] = []
        page = 1
        total: int = 0

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            while True:
                items, total = self._fetch_page(client, page)
                if items is None:
                    break

                for item in items:
                    policy = self._normalize(item)
                    if policy:
                        policies.append(policy)
                    if max_items and len(policies) >= max_items:
                        return policies[:max_items]

                if not items or page * self.page_size >= total:
                    break

                page += 1
                time.sleep(REQUEST_INTERVAL)

        logger.info("data_portal: 총 %d건 수집 (API 전체 %d건)", len(policies), total)
        return policies

    def _fetch_page(self, client: httpx.Client, page: int) -> tuple[list[dict] | None, int]:
        """단일 페이지 API 호출."""
        params = {
            "apiKeyNm": self.api_key,
            "pageNum": page,
            "pageSize": self.page_size,
            "rtnType": "json",
        }
        try:
            resp = client.get(ENDPOINT, params=params)
        except httpx.HTTPError:
            logger.exception("HTTP 요청 실패 (page=%d)", page)
            return None, 0

        if resp.status_code != 200:
            logger.error("HTTP %d: %s", resp.status_code, resp.text[:500])
            return None, 0

        data = resp.json()
        if data.get("resultCode") != 200:
            logger.error("API 오류: %s", data.get("resultMessage", ""))
            return None, 0

        result = data.get("result", {})
        items = result.get("youthPolicyList", [])
        total = result.get("pagging", {}).get("totCount", 0)
        return items, total

    def _normalize(self, item: dict) -> Policy | None:
        """API 응답 단건을 Policy 스키마로 변환."""
        policy_id = item.get("plcyNo", "")
        if not policy_id:
            return None

        title = item.get("plcyNm", "").strip()
        if not title:
            return None

        raw_category = item.get("lclsfNm", "")
        category = normalize_category(raw_category)

        summary = item.get("plcyExplnCn", "").strip()
        description = item.get("etcMttrCn", "").strip() or summary
        benefits = item.get("plcySprtCn", "").strip()
        eligibility = item.get("addAplyQlfcCndCn", "").strip()
        how_to_apply = item.get("plcyAplyMthdCn", "").strip()
        managing_dept = item.get("sprvsnInstCdNm", "").strip()

        min_age = parse_age(item.get("sprtTrgtMinAge", "0"))
        max_age = parse_age(item.get("sprtTrgtMaxAge", "100"))

        biz_start = item.get("bizPrdBgngYmd", "").strip()
        biz_end = item.get("bizPrdEndYmd", "").strip()
        app_period = f"{biz_start} ~ {biz_end}" if biz_start and biz_end else (biz_start or biz_end or "")

        source_url = item.get("aplyUrlAddr", "").strip() or item.get("refUrlAddr1", "").strip()
        region = item.get("zipCd", "").strip() or "전국"

        raw = _build_raw_content_from_fields(
            title=title,
            summary=summary,
            description=description,
            eligibility=eligibility,
            benefits=benefits,
            how_to_apply=how_to_apply,
            app_period=app_period,
            managing_dept=managing_dept,
            region=region,
        )
        return Policy(
            policy_id=policy_id,
            title=title,
            category=category,
            summary=summary,
            description=description,
            eligibility=eligibility,
            benefits=benefits,
            how_to_apply=how_to_apply,
            application_period=app_period,
            managing_department=managing_dept,
            target_age=(min_age, max_age),
            region=region,
            source_url=source_url,
            source_name=self.source_name,
            last_updated=biz_start or "",
            raw_content=raw,
        )


def _build_raw_content_from_fields(
    *,
    title: str,
    summary: str,
    description: str,
    eligibility: str,
    benefits: str,
    how_to_apply: str,
    app_period: str,
    managing_dept: str,
    region: str,
) -> str:
    parts = [
        f"정책명: {title}",
        f"요약: {summary}" if summary else "",
        f"상세설명: {description}" if description and description != summary else "",
        f"신청자격: {eligibility}" if eligibility else "",
        f"지원내용: {benefits}" if benefits else "",
        f"신청방법: {how_to_apply}" if how_to_apply else "",
        f"신청기간: {app_period}" if app_period else "",
        f"주관부처: {managing_dept}" if managing_dept else "",
        f"지역: {region}" if region else "",
    ]
    return "\n".join(p for p in parts if p)
