"""QA 평가 데이터셋 생성 — 정책 원본에서 LLM으로 QA 쌍 자동 생성.

사용법:
    python scripts/generate_qa.py                     # 100개 QA 쌍 생성
    python scripts/generate_qa.py --dry-run            # 선택된 정책만 확인
    python scripts/generate_qa.py --count 50           # 50개 생성
    python scripts/generate_qa.py --min-richness 3     # 풍부도 임계값 낮춤
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import random
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import os  # noqa: E402

os.environ.setdefault("VERTEXAI_PROJECT", os.getenv("VERTEXAI_PROJECT", "rag-qna-eval"))
os.environ.setdefault("VERTEXAI_LOCATION", os.getenv("VERTEXAI_LOCATION", "asia-northeast3"))

from config.settings import settings  # noqa: E402
from src.generation.llm_client import generate  # noqa: E402
from src.ingestion.gcs_client import GCSClient  # noqa: E402
from src.ingestion.policy_store import load_policy_records  # noqa: E402

logger = logging.getLogger(__name__)

TARGET_CATEGORIES = frozenset({"housing", "employment", "education", "welfare", "participation"})

VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
VALID_QA_TYPES = frozenset({"factual", "reasoning", "comparison"})

_COMPARISON_THEMES: list[tuple[str, list[str]]] = [
    ("housing", ["월세", "임대", "전세"]),
    ("housing", ["주택", "대출"]),
    ("employment", ["취업", "일자리", "구직"]),
    ("employment", ["창업", "사업", "벤처"]),
    ("education", ["교육", "훈련", "학습"]),
    ("welfare", ["지원금", "수당", "급여"]),
    ("welfare", ["상담", "멘토", "컨설팅"]),
    ("participation", ["참여", "활동", "봉사"]),
]


def load_policies(path: Path) -> list[dict]:
    """정책 데이터 파일 또는 디렉토리 로드."""
    data = load_policy_records(path)
    logger.info("정책 %d건 로드: %s", len(data), path)
    return data


def load_qa_prompt() -> tuple[str, dict[str, str]]:
    """GCS에서 QA 생성 시스템 프롬프트를 로드한다."""
    gcs = GCSClient(settings.gcs_bucket)
    prompt = gcs.download_text(settings.qa_prompt_gcs_path).strip()
    if not prompt:
        raise RuntimeError(f"QA 프롬프트가 비어 있음: gs://{settings.gcs_bucket}/{settings.qa_prompt_gcs_path}")

    metadata = {
        "gcs_uri": f"gs://{settings.gcs_bucket}/{settings.qa_prompt_gcs_path}",
        "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    return prompt, metadata


def score_policy_richness(policy: dict) -> int:
    """정책 콘텐츠 풍부도 점수 (0~9). 높을수록 QA 생성에 적합."""
    score = 0
    info_fields = [
        "summary",
        "description",
        "eligibility",
        "benefits",
        "how_to_apply",
        "application_period",
        "managing_department",
    ]
    for field in info_fields:
        val = policy.get(field, "")
        if val and str(val).strip():
            score += 1

    raw_len = len(policy.get("raw_content", "") or "")
    if raw_len > 200:
        score += 1
    if raw_len > 500:
        score += 1
    return score


def qa_count_for_policy(policy: dict) -> int:
    """풍부도에 따라 정책당 QA 생성 수 결정 (2~3개)."""
    return 3 if score_policy_richness(policy) >= 6 else 2


def select_policies(
    policies: list[dict],
    target_count: int,
    min_richness: int = 4,
) -> list[tuple[dict, int]]:
    """카테고리 균형 맞춰 정책 선택. (정책, QA수) 튜플 리스트 반환."""
    filtered = [
        p for p in policies if p.get("category") in TARGET_CATEGORIES and score_policy_richness(p) >= min_richness
    ]

    if not filtered:
        logger.error("풍부도 %d 이상 정책 없음. --min-richness 값을 낮춰보세요.", min_richness)
        return []

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in filtered:
        by_cat[p["category"]].append(p)

    for cat_policies in by_cat.values():
        cat_policies.sort(key=score_policy_richness, reverse=True)

    est_qa_per_policy = 2.5
    target_policies = math.ceil(target_count / est_qa_per_policy)
    available_cats = list(by_cat.keys())
    per_cat = max(1, target_policies // len(available_cats))
    remainder = target_policies - per_cat * len(available_cats)

    selected: list[dict] = []
    for cat in sorted(available_cats):
        pool = by_cat[cat]
        top_half = pool[: max(1, len(pool) // 2)]
        quota = per_cat + (1 if remainder > 0 else 0)
        if remainder > 0:
            remainder -= 1
        pick = min(quota, len(top_half))
        selected.extend(random.sample(top_half, pick))

    random.shuffle(selected)
    result = [(p, qa_count_for_policy(p)) for p in selected]
    total_qa = sum(n for _, n in result)
    logger.info(
        "정책 %d건 선택 (총 후보 %d건, 카테고리 %s, 예상 QA %d개)",
        len(result),
        len(filtered),
        sorted(available_cats),
        total_qa,
    )
    return result


def find_comparison_groups(
    policies: list[dict],
    max_groups: int = 8,
    min_richness: int = 3,
) -> list[list[dict]]:
    """같은 카테고리 내에서 유사 정책 그룹을 찾아 비교 QA 생성용으로 반환."""
    filtered = [
        p for p in policies if p.get("category") in TARGET_CATEGORIES and score_policy_richness(p) >= min_richness
    ]

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in filtered:
        by_cat[p["category"]].append(p)

    groups: list[list[dict]] = []
    used_ids: set[str] = set()

    for cat, keywords in _COMPARISON_THEMES:
        if cat not in by_cat:
            continue
        matching = [
            p
            for p in by_cat[cat]
            if any(kw in (p.get("title", "") or "") for kw in keywords) and p.get("policy_id", "") not in used_ids
        ]
        if len(matching) < 2:
            continue
        matching.sort(key=score_policy_richness, reverse=True)
        group = matching[:3]
        groups.append(group)
        for p in group:
            pid = p.get("policy_id", "")
            if pid:
                used_ids.add(pid)

    random.shuffle(groups)
    selected = groups[:max_groups]
    logger.info("비교 그룹 %d개 선택 (총 후보 %d개)", len(selected), len(groups))
    return selected


def plan_difficulty_assignments(qa_counts: list[int]) -> list[list[str]]:
    """난이도 배분 계획 — easy 40%, medium 40%, hard 20%."""
    total = sum(qa_counts)
    n_easy = round(total * 0.4)
    n_medium = round(total * 0.4)
    n_hard = total - n_easy - n_medium

    pool = ["easy"] * n_easy + ["medium"] * n_medium + ["hard"] * n_hard
    random.shuffle(pool)

    assignments: list[list[str]] = []
    idx = 0
    for count in qa_counts:
        assignments.append(pool[idx : idx + count])
        idx += count

    return assignments


def build_qa_prompt(
    policy: dict,
    qa_count: int,
    difficulties: list[str],
    system_prompt: str,
) -> list[dict[str, str]]:
    """개별 정책 QA 프롬프트 빌드."""
    diff_desc = ", ".join(f"{d} 1개" for d in difficulties)

    raw = policy.get("raw_content", "") or ""
    title = policy.get("title", "")
    summary = policy.get("summary", "") or ""
    eligibility = policy.get("eligibility", "") or ""

    policy_text = f"정책명: {title}\n"
    if summary:
        policy_text += f"요약: {summary}\n"
    if eligibility:
        policy_text += f"자격조건: {eligibility}\n"
    policy_text += f"\n원문:\n{raw[:3000]}"

    user_msg = (
        f"아래 정책 정보를 읽고 QA 쌍을 {qa_count}개 생성하세요.\n난이도 배분: {diff_desc}\n\n---\n{policy_text}\n---"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]


def build_comparison_prompt(
    group: list[dict],
    qa_count: int,
    difficulties: list[str],
    system_prompt: str,
) -> list[dict[str, str]]:
    """비교 QA 프롬프트 빌드 — 2~3개 정책 정보를 함께 전달."""
    diff_desc = ", ".join(f"{d} 1개" for d in difficulties)

    policies_text = ""
    for i, policy in enumerate(group, 1):
        title = policy.get("title", "")
        summary = policy.get("summary", "") or ""
        eligibility = policy.get("eligibility", "") or ""
        benefits = policy.get("benefits", "") or ""
        raw = (policy.get("raw_content", "") or "")[:1500]

        policies_text += f"\n### 정책 {i}: {title}\n"
        if summary:
            policies_text += f"요약: {summary}\n"
        if eligibility:
            policies_text += f"자격조건: {eligibility}\n"
        if benefits:
            policies_text += f"혜택: {benefits}\n"
        policies_text += f"원문:\n{raw}\n"

    user_msg = (
        f"아래 {len(group)}개 정책을 **비교**하는 QA 쌍을 {qa_count}개 생성하세요.\n"
        f"난이도 배분: {diff_desc}\n"
        f'qa_type은 반드시 "comparison"으로 지정하세요.\n'
        f"질문은 정책 간 자격조건 차이, 혜택 비교, 상황별 적합한 정책 추천 등을 물어야 합니다.\n"
        f"답변에는 각 정책명을 명시하여 비교하세요.\n\n"
        f"---{policies_text}\n---"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]


def parse_qa_response(raw_content: str) -> list[dict] | None:
    """LLM JSON 응답 파싱 + 검증."""
    text = raw_content.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(1, len(lines)):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("JSON 파싱 실패: %s...", text[:100])
        return None

    if not isinstance(data, list):
        logger.warning("응답이 배열이 아님: %s", type(data))
        return None

    required_keys = {"question", "ground_truth", "difficulty", "qa_type"}
    valid: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not required_keys.issubset(item.keys()):
            continue
        if not item["question"] or not item["ground_truth"]:
            continue
        if item["difficulty"] not in VALID_DIFFICULTIES:
            continue
        if item["qa_type"] not in VALID_QA_TYPES:
            continue
        valid.append(item)

    return valid if valid else None


def generate_qa_for_policy(
    policy: dict,
    qa_count: int,
    difficulties: list[str],
    system_prompt: str,
    model: str = "vertex_ai/gemini-2.5-flash",
) -> list[dict] | None:
    """단일 정책에서 QA 쌍 생성."""
    messages = build_qa_prompt(policy, qa_count, difficulties, system_prompt)

    try:
        resp = generate(messages=messages, model=model, temperature=0.3, max_tokens=2048)
    except RuntimeError as e:
        logger.warning("LLM 호출 실패 [%s]: %s", policy.get("title", ""), e)
        return None

    pairs = parse_qa_response(resp.content)
    if pairs is None:
        logger.warning("QA 파싱 실패 [%s]", policy.get("title", ""))
        return None

    for pair in pairs:
        source_name = policy.get("source_name", "data_portal")
        pair["reference_doc"] = policy.get("raw_path", f"{source_name}/latest.json")
        pair["reference_source"] = source_name
        pair["category"] = policy.get("category", "")
        pair["policy_title"] = policy.get("title", "")
        pair["policy_id"] = policy.get("policy_id", "")

    return pairs


def generate_comparison_qa(
    group: list[dict],
    qa_count: int,
    difficulties: list[str],
    system_prompt: str,
    model: str = "vertex_ai/gemini-2.5-flash",
) -> list[dict] | None:
    """정책 그룹에서 비교 QA 쌍 생성."""
    messages = build_comparison_prompt(group, qa_count, difficulties, system_prompt)

    try:
        resp = generate(messages=messages, model=model, temperature=0.3, max_tokens=2048)
    except RuntimeError as e:
        titles = [p.get("title", "")[:30] for p in group]
        logger.warning("비교 QA LLM 호출 실패 %s: %s", titles, e)
        return None

    pairs = parse_qa_response(resp.content)
    if pairs is None:
        titles = [p.get("title", "")[:30] for p in group]
        logger.warning("비교 QA 파싱 실패 %s", titles)
        return None

    for pair in pairs:
        pair["qa_type"] = "comparison"
        pair["category"] = group[0].get("category", "")
        pair["policy_title"] = " vs ".join(p.get("title", "") for p in group)
        pair["policy_id"] = ",".join(p.get("policy_id", "") for p in group)
        pair["reference_doc"] = group[0].get("raw_path", "")
        pair["reference_source"] = group[0].get("source_name", "data_portal")

    return pairs


def assemble_output(all_pairs: list[dict], model: str, prompt_metadata: dict[str, str]) -> dict:
    """최종 JSON 조립 — 순차 ID, 메타데이터 포함."""
    for i, pair in enumerate(all_pairs, 1):
        pair["id"] = f"q{i:03d}"

    categories = sorted({p["category"] for p in all_pairs if p.get("category")})
    diff_dist = dict(Counter(p["difficulty"] for p in all_pairs))
    type_dist = dict(Counter(p["qa_type"] for p in all_pairs))

    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "domain": "youth_policy",
        "prompt": prompt_metadata,
        "categories": categories,
        "total_count": len(all_pairs),
        "difficulty_distribution": diff_dist,
        "qa_type_distribution": type_dist,
        "samples": all_pairs,
    }


def generate_qa_dataset(
    policies_path: Path,
    output_path: Path,
    target_count: int = 100,
    model: str = "vertex_ai/gemini-2.5-flash",
    min_richness: int = 4,
    *,
    dry_run: bool = False,
) -> dict:
    """QA 데이터셋 생성 메인 오케스트레이션."""
    system_prompt, prompt_metadata = load_qa_prompt()
    policies = load_policies(policies_path)
    if not policies:
        raise RuntimeError("정책 데이터 없음")

    comparison_target = max(2, round(target_count * 0.15))
    individual_target = target_count - comparison_target

    selected = select_policies(policies, individual_target, min_richness)
    if not selected:
        raise RuntimeError("풍부도 기준을 만족하는 정책 없음")

    qa_counts = [n for _, n in selected]
    assignments = plan_difficulty_assignments(qa_counts)

    max_comp_groups = max(1, math.ceil(comparison_target / 2))
    comparison_groups = find_comparison_groups(policies, max_groups=max_comp_groups)
    comp_qa_per_group = max(1, round(comparison_target / max(1, len(comparison_groups)))) if comparison_groups else 0
    comp_assignments = (
        plan_difficulty_assignments([comp_qa_per_group] * len(comparison_groups)) if comparison_groups else []
    )

    if dry_run:
        cat_counts = Counter(p["category"] for p, _ in selected)
        logger.info("=== DRY RUN ===")
        logger.info("프롬프트: %s (%s)", prompt_metadata["gcs_uri"], prompt_metadata["sha256"][:12])
        logger.info("--- 개별 QA ---")
        logger.info("선택 정책 %d건, 카테고리별: %s", len(selected), dict(cat_counts))
        for i, ((p, n), diffs) in enumerate(zip(selected, assignments), 1):
            logger.info(
                "  %2d. [%s] %s (QA %d개, 난이도: %s, 풍부도: %d)",
                i,
                p["category"],
                p["title"][:40],
                n,
                diffs,
                score_policy_richness(p),
            )
        total_individual = sum(len(d) for d in assignments)
        logger.info("예상 개별 QA: %d개", total_individual)
        logger.info("--- 비교 QA ---")
        for i, (group, comp_diffs) in enumerate(zip(comparison_groups, comp_assignments), 1):
            titles = " vs ".join(p["title"][:25] for p in group)
            logger.info("  %2d. [%s] %s (QA %d개)", i, group[0]["category"], titles, len(comp_diffs))
        total_comparison = sum(len(d) for d in comp_assignments)
        logger.info("예상 비교 QA: %d개", total_comparison)
        logger.info("총 예상 QA: %d개", total_individual + total_comparison)
        return {}

    all_pairs: list[dict] = []
    failures = 0

    logger.info("=== 개별 QA 생성 (%d건) ===", len(selected))
    for i, ((policy, qa_n), diffs) in enumerate(zip(selected, assignments), 1):
        logger.info(
            "[%d/%d] %s (QA %d개, 난이도: %s)",
            i,
            len(selected),
            policy["title"][:50],
            qa_n,
            diffs,
        )
        pairs = generate_qa_for_policy(policy, len(diffs), diffs, system_prompt, model)
        if pairs:
            all_pairs.extend(pairs)
            logger.info("  → %d개 QA 쌍 생성", len(pairs))
        else:
            failures += 1
            logger.warning("  → 실패")

        if i < len(selected):
            time.sleep(0.5)

    if comparison_groups:
        logger.info("=== 비교 QA 생성 (%d그룹) ===", len(comparison_groups))
        for i, (group, comp_diffs) in enumerate(zip(comparison_groups, comp_assignments), 1):
            titles = " vs ".join(p["title"][:25] for p in group)
            logger.info("[비교 %d/%d] %s (QA %d개)", i, len(comparison_groups), titles, len(comp_diffs))
            pairs = generate_comparison_qa(group, len(comp_diffs), comp_diffs, system_prompt, model)
            if pairs:
                all_pairs.extend(pairs)
                logger.info("  → %d개 비교 QA 생성", len(pairs))
            else:
                failures += 1
                logger.warning("  → 실패")

            if i < len(comparison_groups):
                time.sleep(0.5)

    if not all_pairs:
        raise RuntimeError("QA 쌍 생성 실패 (0건)")

    output = assemble_output(all_pairs, model, prompt_metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    diff_dist = output["difficulty_distribution"]
    type_dist = output["qa_type_distribution"]
    logger.info(
        "완료: %d개 QA 쌍 생성 (실패 %d건), 난이도 %s, 유형 %s → %s",
        len(all_pairs),
        failures,
        diff_dist,
        type_dist,
        output_path,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="QA 평가 데이터셋 생성")
    parser.add_argument(
        "--input",
        default="data/policies/normalized/all_policies.json",
        help="정책 데이터 JSON 경로",
    )
    parser.add_argument(
        "--output",
        default="data/eval/qa_pairs.json",
        help="출력 JSON 경로",
    )
    parser.add_argument("--count", type=int, default=100, help="목표 QA 쌍 수")
    parser.add_argument("--model", default="vertex_ai/gemini-2.5-flash", help="LiteLLM 모델 ID")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 선택 정책만 확인")
    parser.add_argument("--min-richness", type=int, default=4, help="최소 콘텐츠 풍부도 점수")
    parser.add_argument("--seed", type=int, default=42, help="랜덤 시드")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    random.seed(args.seed)

    generate_qa_dataset(
        policies_path=Path(args.input),
        output_path=Path(args.output),
        target_count=args.count,
        model=args.model,
        min_richness=args.min_richness,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
