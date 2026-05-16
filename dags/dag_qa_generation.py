"""QA 데이터셋 생성 DAG.

스케줄: 수동 트리거 (schedule=None).
정책 원본에서 LLM을 이용해 QA 쌍을 생성한다.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from airflow.models.param import Param
from utils.notifications import on_failure_callback

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "rag-pipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "on_failure_callback": on_failure_callback,
}

REPO_ROOT = Path("/opt/rag-pipeline")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ALLOWED_DATA_DIR = REPO_ROOT / "data"


def _validate_path(raw: str, base: Path) -> Path:
    """경로를 base 디렉토리 내부로 제한한다."""
    base_resolved = base.resolve()
    resolved = (base_resolved / raw).resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"허용 범위 밖 경로: {raw}")
    return resolved


@dag(
    dag_id="qa_generation",
    default_args=DEFAULT_ARGS,
    description="정책 데이터에서 QA 쌍 생성 (LLM 기반)",
    schedule=None,
    start_date=pendulum.datetime(2026, 4, 25, tz="Asia/Seoul"),
    catchup=False,
    tags=["qa", "manual"],
    params={
        "target_count": Param(default=100, type="integer", description="생성할 QA 쌍 수"),
        "model": Param(
            default="vertex_ai/gemini-2.5-flash",
            type="string",
            description="QA 생성에 사용할 LLM 모델 ID",
        ),
        "policies_path": Param(
            default="policies/normalized/all_policies.json",
            type="string",
            description="정책 원본 파일 (data/ 기준 상대경로, 예: policies/normalized/all_policies.json)",
        ),
        "output_path": Param(
            default="eval/qa_pairs.json",
            type="string",
            description="QA 데이터셋 출력 경로 (data/ 기준 상대경로, 예: eval/qa_pairs.json)",
        ),
        "dry_run": Param(default=False, type="boolean", description="드라이런 (LLM 호출 없이 테스트)"),
    },
)
def qa_generation():
    @task()
    def generate_qa(**context) -> dict:  # noqa: ARG001
        """LLM으로 QA 데이터셋 생성."""
        from scripts.generate_qa import generate_qa_dataset

        params = context["params"]
        policies_path = _validate_path(params["policies_path"], ALLOWED_DATA_DIR)
        output_path = _validate_path(params["output_path"], ALLOWED_DATA_DIR)

        result = generate_qa_dataset(
            policies_path=policies_path,
            output_path=output_path,
            target_count=params["target_count"],
            model=params["model"],
            dry_run=params["dry_run"],
        )
        logger.info("QA 생성 완료: %s", result)
        return result

    @task()
    def upload_to_gcs(gen_result: dict, **context) -> str:  # noqa: ARG001
        """생성된 QA 데이터셋을 GCS에 업로드."""
        from config.settings import settings
        from src.ingestion.gcs_client import GCSClient

        output_path = _validate_path(context["params"]["output_path"], ALLOWED_DATA_DIR)
        gcs = GCSClient(settings.gcs_bucket)
        gcs_path = f"eval/{output_path.name}"
        gcs.upload_file(output_path, gcs_path)

        gcs_uri = f"gs://{settings.gcs_bucket}/{gcs_path}"
        logger.info("GCS 업로드 완료: %s", gcs_uri)
        return gcs_uri

    @task()
    def sync_qa_metadata(gcs_uri: str, **context) -> dict:  # noqa: ARG001
        """QA 데이터셋 GCS 객체와 데이터셋 메타데이터를 MongoDB에 동기화."""
        from config.settings import settings
        from src.ingestion.gcs_catalog import sync_gcs_objects_to_mongo
        from src.ingestion.mongo_client import PolicyMetadataStore

        output_path = _validate_path(context["params"]["output_path"], ALLOWED_DATA_DIR)
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        object_name = f"eval/{output_path.name}"
        dataset_id = f"{data.get('domain', 'qa')}:{data.get('version', 'unknown')}:{data.get('generated_at', '')}"
        store = PolicyMetadataStore()
        try:
            synced_assets = sync_gcs_objects_to_mongo(
                [object_name],
                bucket=settings.gcs_bucket,
                mongo=store,
                metadata_overrides={
                    object_name: {
                        "asset_type": "qa_dataset",
                        "record_count": data.get("total_count"),
                    }
                },
            )
            store.upsert_qa_dataset(
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
            qa_count = store.sync_qa_pairs(data.get("samples", []), dataset_id)
        finally:
            store.close()

        logger.info("QA MongoDB 동기화 완료: 메타데이터 + %d건 QA 쌍 → %s", qa_count, gcs_uri)
        return {"gcs_assets_synced": synced_assets, "dataset_id": dataset_id, "qa_pairs_synced": qa_count}

    result = generate_qa()
    uploaded = upload_to_gcs(result)
    sync_qa_metadata(uploaded)


qa_generation()
