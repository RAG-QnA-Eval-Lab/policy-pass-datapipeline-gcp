"""공공데이터포털 청년정책 API 연결 검증.

공공데이터포털(data.go.kr) 서비스 15143273 → 온통청년 Open API 경유.
엔드포인트: https://www.youthcenter.go.kr/go/ythip/getPlcy
인증 파라미터: apiKeyNm (공공데이터포털에서 발급받은 키)
"""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.environ.get("DATA_PORTAL_API_KEY", "")
ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"


def verify_connection() -> bool:
    """기본 연결 + 인증 확인 (1건 JSON)."""
    print("[1/4] API 연결 테스트")
    print(f"  endpoint: {ENDPOINT}")
    print(f"  api_key: {API_KEY[:8]}...{API_KEY[-4:]}" if len(API_KEY) > 12 else "  api_key: (미설정)")

    if not API_KEY:
        print("  [FAIL] DATA_PORTAL_API_KEY가 .env에 설정되지 않았습니다.")
        return False

    params = {"apiKeyNm": API_KEY, "pageNum": 1, "pageSize": 1, "rtnType": "json"}

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(ENDPOINT, params=params)
        print(f"  status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"  [FAIL] HTTP {resp.status_code}: {resp.text[:500]}")
            return False

        data = resp.json()
        code = data.get("resultCode")
        msg = data.get("resultMessage", "")
        print(f"  resultCode: {code}")
        print(f"  resultMessage: {msg}")

        if code == 200:
            total = data.get("result", {}).get("pagging", {}).get("totCount", "N/A")
            print(f"  전체 정책 수: {total}")
            print("  [OK] 연결 성공")
            return True

        print(f"  [FAIL] API 오류: {msg}")
        return False


def verify_data_structure() -> bool:
    """응답 데이터 구조 확인 (3건)."""
    print("\n[2/4] 데이터 구조 확인 (3건)")

    params = {"apiKeyNm": API_KEY, "pageNum": 1, "pageSize": 3, "rtnType": "json"}

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(ENDPOINT, params=params)
        data = resp.json()
        items = data.get("result", {}).get("youthPolicyList", [])
        print(f"  수신 건수: {len(items)}")

        if not items:
            print("  [FAIL] youthPolicyList 비어 있음")
            return False

        sample = items[0]
        print("\n  --- 첫 번째 정책 주요 필드 ---")
        key_fields = [
            "plcyNo",
            "plcyNm",
            "lclsfNm",
            "mclsfNm",
            "plcyExplnCn",
            "plcySprtCn",
            "sprvsnInstCdNm",
            "operInstCdNm",
            "sprtTrgtMinAge",
            "sprtTrgtMaxAge",
            "bizPrdBgngYmd",
            "bizPrdEndYmd",
            "aplyUrlAddr",
            "refUrlAddr1",
            "zipCd",
        ]
        for key in key_fields:
            val = sample.get(key, "(없음)")
            val_str = str(val).strip()
            if len(val_str) > 80:
                val_str = val_str[:80] + "..."
            print(f"    {key}: {val_str}")

        all_fields = list(sample.keys())
        print(f"\n  전체 필드 수: {len(all_fields)}")
        return True


def verify_pagination() -> bool:
    """페이지네이션 동작 확인."""
    print("\n[3/4] 페이지네이션 확인")

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        params1 = {"apiKeyNm": API_KEY, "pageNum": 1, "pageSize": 2, "rtnType": "json"}
        resp1 = client.get(ENDPOINT, params=params1)
        data1 = resp1.json()
        items1 = data1.get("result", {}).get("youthPolicyList", [])
        total = data1.get("result", {}).get("pagging", {}).get("totCount", 0)

        params2 = {"apiKeyNm": API_KEY, "pageNum": 2, "pageSize": 2, "rtnType": "json"}
        resp2 = client.get(ENDPOINT, params=params2)
        data2 = resp2.json()
        items2 = data2.get("result", {}).get("youthPolicyList", [])

        ids1 = {item.get("plcyNo") for item in items1}
        ids2 = {item.get("plcyNo") for item in items2}
        overlap = ids1 & ids2

        print(f"  전체: {total}건")
        print(f"  페이지1: {[i.get('plcyNo', '')[-6:] for i in items1]}")
        print(f"  페이지2: {[i.get('plcyNo', '')[-6:] for i in items2]}")
        print(f"  중복: {len(overlap)}건")

        if not overlap and len(items1) == 2 and len(items2) == 2:
            print("  [OK] 페이지네이션 정상")
            return True

        print("  [WARN] 페이지네이션 확인 필요")
        return len(items1) > 0


def verify_search() -> bool:
    """키워드/카테고리 검색 확인."""
    print("\n[4/4] 검색 필터 테스트")

    with httpx.Client(timeout=30, follow_redirects=True) as client:
        params = {
            "apiKeyNm": API_KEY,
            "pageNum": 1,
            "pageSize": 3,
            "rtnType": "json",
            "lclsfNm": "주거",
        }
        resp = client.get(ENDPOINT, params=params)
        data = resp.json()
        items = data.get("result", {}).get("youthPolicyList", [])
        total = data.get("result", {}).get("pagging", {}).get("totCount", 0)

        print(f"  대분류='주거' 검색 결과: {total}건")
        for i, item in enumerate(items):
            title = item.get("plcyNm", "(제목 없음)")
            cat = item.get("mclsfNm", "")
            print(f"    [{i + 1}] [{cat}] {title}")

        if total > 0 and len(items) > 0:
            print("  [OK] 카테고리 필터 정상")
            return True

        print("  [WARN] 검색 결과 없음")
        return False


def main() -> None:
    print("=" * 60)
    print("공공데이터포털 청년정책 API 검증")
    print(f"endpoint: {ENDPOINT}")
    print("=" * 60 + "\n")

    results = {
        "연결": verify_connection(),
        "데이터구조": False,
        "페이지네이션": False,
        "검색필터": False,
    }

    if results["연결"]:
        results["데이터구조"] = verify_data_structure()
        results["페이지네이션"] = verify_pagination()
        results["검색필터"] = verify_search()

    print("\n" + "=" * 60)
    print("검증 결과")
    print("=" * 60)
    for name, passed in results.items():
        print(f"  {name:12s}: {'PASS' if passed else 'FAIL'}")

    all_pass = all(results.values())
    if all_pass:
        print("\n모든 검증 통과. 수집기 구현 가능.")
    else:
        print("\n일부 검증 실패. 위 로그를 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
