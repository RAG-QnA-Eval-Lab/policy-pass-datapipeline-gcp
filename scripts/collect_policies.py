"""정책 수집 CLI — 수집기 → JSON 저장 + GCS 업로드 + MongoDB 메타데이터.

사용법:
    python scripts/collect_policies.py --all
    python scripts/collect_policies.py --source data_portal --max-items 50
    python scripts/collect_policies.py --all --skip-gcs --skip-mongo   # 로컬 테스트
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from config.settings import settings  # noqa: E402
from src.ingestion.collectors.base import BaseCollector, policy_to_dict  # noqa: E402
from src.ingestion.collectors.data_portal import DataPortalCollector  # noqa: E402
from src.ingestion.policy_store import rebuild_policy_views_from_raw  # noqa: E402
from src.ingestion.utils import save_policies_json  # noqa: E402

logger = logging.getLogger(__name__)

COLLECTORS: dict[str, type[BaseCollector]] = {
    "data_portal": DataPortalCollector,
}

_MONGO_FIELDS: tuple[str, ...] = (
    "policy_id",
    "title",
    "category",
    "summary",
    "description",
    "eligibility",
    "benefits",
    "how_to_apply",
    "application_period",
    "managing_department",
    "region",
    "source_url",
    "source_name",
    "last_updated",
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _raw_storage_paths(output_dir: str | Path, source: str) -> tuple[Path, Path]:
    root = Path(output_dir) / source
    latest_path = root / "latest.json"
    snapshot_path = root / "snapshots" / f"{_timestamp()}.json"
    return latest_path, snapshot_path


def _json_record_count(path: str | Path) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict) and isinstance(data.get("policies"), list):
        return len(data["policies"])
    return None


def run_collection(
    source: str,
    max_items: int | None = None,
    output_dir: str = "data/policies/raw",
    *,
    skip_gcs: bool = False,
    skip_mongo: bool = False,
) -> None:
    collector_cls = COLLECTORS.get(source)
    if not collector_cls:
        logger.error("알 수 없는 소스: %s (사용 가능: %s)", source, list(COLLECTORS.keys()))
        sys.exit(1)

    logger.info("수집 시작: %s (max_items=%s)", source, max_items)
    collector = collector_cls()
    valid_policies, errors = collector.collect_validated(max_items=max_items)

    if not valid_policies:
        logger.warning("수집된 정책 없음")
        return

    policy_dicts = [policy_to_dict(p) for p in valid_policies]
    latest_path, snapshot_path = _raw_storage_paths(output_dir, source)
    relative_raw_path = str(latest_path.relative_to(Path(output_dir)))
    for policy in policy_dicts:
        policy["raw_path"] = relative_raw_path

    # 1. 로컬 JSON 저장 (캐시)
    save_policies_json(policy_dicts, latest_path)
    save_policies_json(policy_dicts, snapshot_path)
    logger.info("로컬 저장 완료: %d건 → %s (snapshot: %s)", len(valid_policies), latest_path, snapshot_path)

    derived_paths = rebuild_policy_views_from_raw(Path(output_dir), Path(output_dir).parent)
    logger.info("정규화 데이터 재생성 완료: %s", derived_paths["all_policies_path"])

    # 2. GCS 업로드
    gcs_uri = None
    uploaded_gcs_objects: list[str] = []
    gcs_asset_overrides: dict[str, dict] = {}
    if not skip_gcs:
        try:
            from src.ingestion.gcs_client import GCSClient

            gcs = GCSClient(settings.gcs_bucket)
            gcs_latest_path = f"policies/raw/{source}/latest.json"
            gcs_snapshot_path = f"policies/raw/{source}/snapshots/{snapshot_path.name}"
            gcs_uri = gcs.upload_json(gcs_latest_path, policy_dicts)
            gcs.upload_json(gcs_snapshot_path, policy_dicts)
            uploaded_gcs_objects.extend([gcs_latest_path, gcs_snapshot_path])
            gcs_asset_overrides[gcs_latest_path] = {
                "asset_type": "raw_policy",
                "related_source": source,
                "record_count": len(policy_dicts),
            }
            gcs_asset_overrides[gcs_snapshot_path] = {
                "asset_type": "raw_policy",
                "related_source": source,
                "record_count": len(policy_dicts),
            }
            logger.info("GCS 업로드 완료: %s", gcs_uri)

            normalized_paths = [
                ("policies/processed/all_policies.json", derived_paths["all_policies_path"]),
                ("policies/processed/manifest.json", derived_paths["manifest_path"]),
            ]
            normalized_paths.extend(
                (f"policies/processed/by_source/{name}.json", path)
                for name, path in derived_paths["by_source_paths"].items()
            )
            normalized_paths.extend(
                (f"policies/processed/by_category/{name}.json", path)
                for name, path in derived_paths["by_category_paths"].items()
            )

            for remote_path, local_file in normalized_paths:
                gcs.upload_file(Path(local_file), remote_path)
                uploaded_gcs_objects.append(remote_path)
                gcs_asset_overrides[remote_path] = {
                    "asset_type": "processed_policy",
                    "related_source": source if "/by_source/" in remote_path else None,
                    "record_count": _json_record_count(local_file),
                }
        except Exception:
            logger.exception("GCS 업로드 실패 — 로컬 파일은 저장됨")

    # 3. MongoDB 메타데이터 upsert
    if not skip_mongo:
        try:
            from src.ingestion.mongo_client import PolicyMetadataStore

            mongo = PolicyMetadataStore()
            gcs_raw_path = f"gs://{settings.gcs_bucket}/policies/raw/{source}/latest.json"
            metadata_list = [
                {
                    **{k: p.get(k, "") for k in _MONGO_FIELDS},
                    "gcs_path": gcs_raw_path,
                    "status": "active",
                }
                for p in policy_dicts
                if p.get("policy_id")
            ]
            upserted = mongo.upsert_policies_batch(metadata_list)
            logger.info("MongoDB upsert 완료: %d건", upserted)

            # 4. 수집 이력 기록
            mongo.log_ingestion(
                source=source,
                collected_count=len(policy_dicts),
                valid_count=len(valid_policies),
                gcs_paths=[gcs_uri] if gcs_uri else [],
            )

            if uploaded_gcs_objects:
                from src.ingestion.gcs_catalog import sync_gcs_objects_to_mongo

                synced = sync_gcs_objects_to_mongo(
                    uploaded_gcs_objects,
                    bucket=settings.gcs_bucket,
                    mongo=mongo,
                    metadata_overrides=gcs_asset_overrides,
                )
                logger.info("GCS asset catalog 동기화 완료: %d건", synced)
            mongo.close()
        except Exception:
            logger.exception("MongoDB 연동 실패 — 로컬 파일은 저장됨")

    if errors:
        logger.warning("검증 오류 %d건", len(errors))
        for e in errors[:5]:
            logger.warning("  - %s: %s", e["policy_id"], e["errors"])


def run_all_collections(
    max_items: int | None = None,
    output_dir: str = "data/policies/raw",
    *,
    skip_gcs: bool = False,
    skip_mongo: bool = False,
) -> dict[str, str]:
    """전체 소스 수집 실행. 소스별 성공/실패 결과 dict 반환."""
    results: dict[str, str] = {}
    for source in COLLECTORS:
        try:
            run_collection(
                source,
                max_items=max_items,
                output_dir=output_dir,
                skip_gcs=skip_gcs,
                skip_mongo=skip_mongo,
            )
            results[source] = "success"
        except Exception:
            results[source] = "failed"
            logger.exception("수집 실패: %s", source)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="정책 데이터 수집")
    parser.add_argument("--source", choices=list(COLLECTORS.keys()), help="수집할 소스")
    parser.add_argument("--all", action="store_true", help="모든 소스 수집")
    parser.add_argument("--max-items", type=int, default=None, help="최대 수집 건수")
    parser.add_argument("--output-dir", default="data/policies/raw", help="출력 디렉토리")
    parser.add_argument("--skip-gcs", action="store_true", help="GCS 업로드 건너뛰기 (로컬 테스트)")
    parser.add_argument("--skip-mongo", action="store_true", help="MongoDB 연동 건너뛰기 (로컬 테스트)")
    args = parser.parse_args()

    if args.all:
        run_all_collections(
            max_items=args.max_items,
            output_dir=args.output_dir,
            skip_gcs=args.skip_gcs,
            skip_mongo=args.skip_mongo,
        )
    elif args.source:
        run_collection(
            args.source,
            max_items=args.max_items,
            output_dir=args.output_dir,
            skip_gcs=args.skip_gcs,
            skip_mongo=args.skip_mongo,
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
