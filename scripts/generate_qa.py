"""QA 평가 데이터셋 생성 — 정책 원본에서 GPT-4o-mini로 QA 쌍 자동 생성.

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

TARGET_CATEGORIES = frozenset({"housing", "employment", "education", "welfare"})

VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
VALID_QA_TYPES = frozenset({"factual", "reasoning", "comparison"})


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
        "summary", "description", "eligibility", "benefits",
        "how_to_apply", "application_period", "managing_department",
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


def select_policies(
    policies: list[dict],
    target_count: int,
    qa_per_policy: int = 2,
    min_richness: int = 4,
) -> list[dict]:
    """카테고리 균형 맞춰 정책 선택. participation 제외."""
    filtered = [
        p for p in policies
        if p.get("category") in TARGET_CATEGORIES
        and score_policy_richness(p) >= min_richness
    ]

    if not filtered:
        logger.error("풍부도 %d 이상 정책 없음. --min-richness 값을 낮춰보세요.", min_richness)
        return []

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in filtered:
        by_cat[p["category"]].append(p)

    for cat_policies in by_cat.values():
        cat_policies.sort(key=score_policy_richness, reverse=True)

    target_policies = math.ceil(target_count / qa_per_policy)
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
    logger.info(
        "정책 %d건 선택 (총 후보 %d건, 카테고리 %s)",
        len(selected), len(filtered), sorted(available_cats),
    )
    return selected


def plan_difficulty_assignments(
    target_count: int, num_policies: int,
) -> list[list[str]]:
    """난이도 배분 계획 — easy 40%, medium 40%, hard 20%."""
    n_easy = round(target_count * 0.4)
    n_medium = round(target_count * 0.4)
    n_hard = target_count - n_easy - n_medium

    pool = (
        ["easy"] * n_easy
        + ["medium"] * n_medium
        + ["hard"] * n_hard
    )
    random.shuffle(pool)

    assignments: list[list[str]] = []
    idx = 0
    for _ in range(num_policies):
        remaining_policies = num_policies - len(assignments)
        remaining_items = len(pool) - idx
        if remaining_policies <= 0:
            break
        chunk_size = max(2, math.ceil(remaining_items / remaining_policies))
        chunk_size = min(chunk_size, 3, remaining_items)
        assignments.append(pool[idx : idx + chunk_size])
        idx += chunk_size

    return assignments


def build_qa_prompt(
    policy: dict, qa_count: int, difficulties: list[str], system_prompt: str,
) -> list[dict[str, str]]:
    """GPT-4o-mini 프롬프트 빌드."""
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
        f"아래 정책 정보를 읽고 QA 쌍을 {qa_count}개 생성하세요.\n"
        f"난이도 배분: {diff_desc}\n\n"
        f"---\n{policy_text}\n---"
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

    qa_per_policy = 2
    selected = select_policies(policies, target_count, qa_per_policy, min_richness)
    if not selected:
        raise RuntimeError("풍부도 기준을 만족하는 정책 없음")

    assignments = plan_difficulty_assignments(target_count, len(selected))

    if dry_run:
        cat_counts = Counter(p["category"] for p in selected)
        logger.info("=== DRY RUN ===")
        logger.info("프롬프트: %s (%s)", prompt_metadata["gcs_uri"], prompt_metadata["sha256"][:12])
        logger.info("선택 정책 %d건, 카테고리별: %s", len(selected), dict(cat_counts))
        for i, (p, diffs) in enumerate(zip(selected, assignments), 1):
            logger.info(
                "  %2d. [%s] %s (난이도: %s, 풍부도: %d)",
                i, p["category"], p["title"][:40], diffs, score_policy_richness(p),
            )
        total_planned = sum(len(d) for d in assignments)
        logger.info("예상 QA 쌍: %d개", total_planned)
        return {}

    all_pairs: list[dict] = []
    failures = 0

    for i, (policy, diffs) in enumerate(zip(selected, assignments), 1):
        logger.info(
            "[%d/%d] %s (난이도: %s)",
            i, len(selected), policy["title"][:50], diffs,
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
        len(all_pairs), failures, diff_dist, type_dist, output_path,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="QA 평가 데이터셋 생성")
    parser.add_argument(
        "--input", default="data/policies/normalized/all_policies.json",
        help="정책 데이터 JSON 경로",
    )
    parser.add_argument(
        "--output", default="data/eval/qa_pairs.json",
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
