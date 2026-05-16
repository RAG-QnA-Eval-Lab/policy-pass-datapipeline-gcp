"""MongoDB 메타데이터 클라이언트 — 정책 메타데이터 CRUD + 수집 이력."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database

from config.settings import settings

logger = logging.getLogger(__name__)


class PolicyMetadataStore:
    """MongoDB 정책 메타데이터 저장소."""

    def __init__(self, uri: str | None = None, db_name: str | None = None) -> None:
        self._uri = uri or settings.mongodb_uri
        self._db_name = db_name or settings.mongodb_db
        self._client: MongoClient | None = None

    @property
    def client(self) -> MongoClient:
        if self._client is None:
            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
        return self._client

    @property
    def db(self) -> Database:
        return self.client[self._db_name]

    @property
    def policies(self) -> Collection:
        return self.db["policies"]

    @property
    def ingestion_logs(self) -> Collection:
        return self.db["ingestion_logs"]

    @property
    def gcs_assets(self) -> Collection:
        return self.db["gcs_assets"]

    @property
    def qa_datasets(self) -> Collection:
        return self.db["qa_datasets"]

    @property
    def qa_pairs(self) -> Collection:
        return self.db["qa_pairs"]

    @property
    def api_usage_logs(self) -> Collection:
        return self.db["api_usage_logs"]

    def ensure_indexes(self) -> None:
        self.policies.create_index("policy_id", unique=True)
        self.policies.create_index("category")
        self.policies.create_index("source_name")
        self.policies.create_index("updated_at")
        self.ingestion_logs.create_index("source")
        self.ingestion_logs.create_index("created_at")
        self.gcs_assets.create_index("gcs_uri", unique=True)
        self.gcs_assets.create_index("asset_type")
        self.gcs_assets.create_index("object_name")
        self.gcs_assets.create_index("synced_at")
        self.qa_datasets.create_index("dataset_id", unique=True)
        self.qa_datasets.create_index("generated_at")
        self.qa_datasets.create_index("gcs_uri")
        self.qa_pairs.create_index("id", unique=True)
        self.qa_pairs.create_index("dataset_id")
        self.qa_pairs.create_index("category")
        self.qa_pairs.create_index("difficulty")
        self.api_usage_logs.create_index("timestamp")
        self.api_usage_logs.create_index("request_id")
        self.api_usage_logs.create_index("model")
        self.api_usage_logs.create_index("status")

    def upsert_policy(self, metadata: dict) -> None:
        """정책 메타데이터 upsert (policy_id 기준)."""
        policy_id = metadata.get("policy_id")
        if not policy_id:
            logger.warning("policy_id 없는 메타데이터 무시: %s", metadata.get("title", ""))
            return
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.policies.update_one({"policy_id": policy_id}, {"$set": metadata}, upsert=True)

    def upsert_policies_batch(self, metadata_list: list[dict]) -> int:
        """정책 메타데이터 배치 upsert (bulk_write)."""
        now = datetime.now(timezone.utc).isoformat()
        ops = [
            UpdateOne(
                {"policy_id": m["policy_id"]},
                {"$set": {**m, "updated_at": now}},
                upsert=True,
            )
            for m in metadata_list
            if m.get("policy_id")
        ]
        if not ops:
            return 0
        result = self.policies.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    def find_by_id(self, policy_id: str) -> dict | None:
        return self.policies.find_one({"policy_id": policy_id}, {"_id": 0})

    def find_by_category(self, category: str, skip: int = 0, limit: int = 100) -> list[dict]:
        cursor = self.policies.find({"category": category}, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit)
        return list(cursor)

    def list_all(self, skip: int = 0, limit: int = 100) -> list[dict]:
        cursor = self.policies.find({}, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit)
        return list(cursor)

    def count(self, query: dict | None = None) -> int:
        return self.policies.count_documents(query or {})

    def upsert_gcs_asset(self, asset: dict) -> None:
        """GCS 객체 catalog 메타데이터 upsert (gcs_uri 기준)."""
        gcs_uri = asset.get("gcs_uri")
        if not gcs_uri:
            logger.warning("gcs_uri 없는 GCS asset 무시: %s", asset.get("object_name", ""))
            return
        now = datetime.now(timezone.utc).isoformat()
        self.gcs_assets.update_one(
            {"gcs_uri": gcs_uri},
            {"$set": {**asset, "synced_at": now}},
            upsert=True,
        )

    def upsert_gcs_assets_batch(self, assets: list[dict]) -> int:
        """GCS 객체 catalog 메타데이터 배치 upsert."""
        now = datetime.now(timezone.utc).isoformat()
        ops = [
            UpdateOne(
                {"gcs_uri": asset["gcs_uri"]},
                {"$set": {**asset, "synced_at": now}},
                upsert=True,
            )
            for asset in assets
            if asset.get("gcs_uri")
        ]
        if not ops:
            return 0
        result = self.gcs_assets.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    def list_gcs_assets(self, query: dict | None = None, skip: int = 0, limit: int = 100) -> list[dict]:
        cursor = self.gcs_assets.find(query or {}, {"_id": 0}).skip(skip).limit(limit)
        return list(cursor)

    def upsert_qa_dataset(self, metadata: dict) -> None:
        """QA 데이터셋 버전/생성정보 메타데이터 upsert."""
        dataset_id = metadata.get("dataset_id") or metadata.get("gcs_uri") or metadata.get("version")
        if not dataset_id:
            logger.warning("dataset_id 없는 QA dataset 메타데이터 무시")
            return
        now = datetime.now(timezone.utc).isoformat()
        self.qa_datasets.update_one(
            {"dataset_id": dataset_id},
            {"$set": {**metadata, "dataset_id": dataset_id, "updated_at": now}},
            upsert=True,
        )

    def sync_qa_pairs(self, samples: list[dict], dataset_id: str) -> int:
        """QA 쌍을 qa_pairs 컬렉션에 동기화. 기존 동일 dataset_id 데이터는 교체."""
        self.qa_pairs.delete_many({"dataset_id": dataset_id})
        if not samples:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        docs = [{**s, "dataset_id": dataset_id, "synced_at": now} for s in samples]
        result = self.qa_pairs.insert_many(docs)
        count = len(result.inserted_ids)
        logger.info("qa_pairs %d건 동기화 (dataset_id=%s)", count, dataset_id)
        return count

    def log_ingestion(
        self,
        source: str,
        collected_count: int,
        valid_count: int,
        status: str = "success",
        gcs_paths: list[str] | None = None,
        errors: list[dict] | None = None,
    ) -> None:
        """수집 이력 기록."""
        self.ingestion_logs.insert_one(
            {
                "source": source,
                "collected_count": collected_count,
                "valid_count": valid_count,
                "status": status,
                "gcs_paths": gcs_paths or [],
                "errors": errors or [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def log_api_usage(self, record: dict) -> None:
        """LLM API 사용량/비용 로그 기록."""
        doc = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
        self.api_usage_logs.insert_one(doc)

    def get_data_pipeline_status(self) -> dict:
        """헬스체크/Grafana용 데이터 적재 상태 요약."""
        latest = self.ingestion_logs.find_one({}, {"_id": 0}, sort=[("created_at", -1)])

        pipeline = [
            {"$sort": {"created_at": -1}},
            {
                "$group": {
                    "_id": "$source",
                    "last_run": {"$first": {"$ifNull": ["$created_at", "$finished_at"]}},
                    "status": {"$first": "$status"},
                    "count": {"$first": {"$ifNull": ["$valid_count", {"$ifNull": ["$total", "$collected_count"]}]}},
                }
            },
        ]
        sources = {
            doc["_id"]: {"last_run": doc.get("last_run"), "status": doc.get("status"), "count": doc.get("count", 0)}
            for doc in self.ingestion_logs.aggregate(pipeline)
            if doc.get("_id")
        }

        return {
            "last_ingestion": (latest or {}).get("created_at") or (latest or {}).get("finished_at"),
            "total_policies": self.count(),
            "index_sync_status": "unknown",
            "sources": sources,
        }

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
