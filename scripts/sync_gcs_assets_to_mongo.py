"""GCS 객체 catalog를 MongoDB gcs_assets 컬렉션에 동기화.

사용법:
    python scripts/sync_gcs_assets_to_mongo.py
    python scripts/sync_gcs_assets_to_mongo.py --prefix policies/processed/ --prefix eval/
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from config.settings import settings  # noqa: E402
from src.ingestion.gcs_catalog import sync_gcs_prefixes_to_mongo  # noqa: E402
from src.ingestion.mongo_client import PolicyMetadataStore  # noqa: E402

DEFAULT_PREFIXES = [
    "policies/raw/",
    "policies/processed/",
    "eval/",
    "prompts/",
    "results/",
    "index/",
]


def _sync_local_qa_dataset_metadata(mongo: PolicyMetadataStore, qa_file: Path, bucket: str) -> bool:
    if not qa_file.exists():
        return False

    with open(qa_file, encoding="utf-8") as f:
        data = json.load(f)

    gcs_uri = f"gs://{bucket}/eval/{qa_file.name}"
    dataset_id = f"{data.get('domain', 'qa')}:{data.get('version', 'unknown')}:{data.get('generated_at', '')}"
    mongo.upsert_qa_dataset(
        {
            "dataset_id": dataset_id,
            "gcs_uri": gcs_uri,
            "version": data.get("version"),
            "generated_at": data.get("generated_at"),
            "model": data.get("model"),
            "domain": data.get("domain"),
            "categories": data.get("categories"),
            "total_count": data.get("total_count"),
            "difficulty_distribution": data.get("difficulty_distribution"),
            "qa_type_distribution": data.get("qa_type_distribution"),
            "prompt": data.get("prompt"),
        }
    )
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="GCS object catalog를 MongoDB에 동기화")
    parser.add_argument(
        "--prefix",
        action="append",
        dest="prefixes",
        help="동기화할 GCS prefix. 여러 번 지정 가능. 기본은 운영 주요 prefix 전체.",
    )
    parser.add_argument("--bucket", default=settings.gcs_bucket, help="GCS 버킷명")
    parser.add_argument("--mongodb-uri", default=None, help="MongoDB URI override")
    parser.add_argument(
        "--qa-file",
        default="data/eval/qa_pairs.json",
        help="qa_datasets 요약 메타데이터로 동기화할 로컬 QA JSON 경로",
    )
    args = parser.parse_args()

    prefixes = args.prefixes or DEFAULT_PREFIXES
    mongo = PolicyMetadataStore(uri=args.mongodb_uri)
    try:
        mongo.ensure_indexes()
        synced = sync_gcs_prefixes_to_mongo(prefixes, bucket=args.bucket, mongo=mongo)
        qa_synced = _sync_local_qa_dataset_metadata(mongo, Path(args.qa_file), args.bucket)
    finally:
        mongo.close()
    print(f"GCS asset catalog 동기화 완료: {synced}건 → {settings.mongodb_db}.gcs_assets")
    if qa_synced:
        print(f"QA dataset 메타데이터 동기화 완료 → {settings.mongodb_db}.qa_datasets")


if __name__ == "__main__":
    main()
