"""데이터 수집 + FAISS 인덱스 빌드 DAG.

스케줄: 매일 02:00 KST (17:00 UTC).
흐름: 전체 소스 수집 → GCS 인덱스 빌드 → Cloud Run 재시작 (GCP)
                                       → DataSync 동기화 → AWS 배포 트리거
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.decorators import dag, task
from utils.cloud_run import restart_cloud_run_service
from utils.notifications import on_failure_callback

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "rag-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "on_failure_callback": on_failure_callback,
}

REPO_ROOT = Path("/opt/rag-pipeline")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
RAW_OUTPUT_DIR = REPO_ROOT / "data" / "policies" / "raw"

_AWS_DEPLOY_OWNER = os.environ.get("AWS_DEPLOY_OWNER", "Daehyun-Bigbread")
_AWS_DEPLOY_REPO = os.environ.get("AWS_DEPLOY_REPO", "RAG-QA-pipeline-AWS")


@dag(
    dag_id="collect_and_index",
    default_args=DEFAULT_ARGS,
    description="정책 수집 → GCS 인덱스 빌드 → Cloud Run 재시작 + AWS 동기화/배포",
    schedule="0 17 * * *",
    start_date=pendulum.datetime(2026, 4, 25, tz="Asia/Seoul"),
    catchup=False,
    tags=["ingestion", "daily"],
    max_active_runs=1,
)
def collect_and_index():
    @task()
    def collect_all_sources() -> dict:
        """모든 수집기 실행 → 로컬 + GCS + MongoDB 저장."""
        from scripts.collect_policies import run_all_collections

        os.chdir(REPO_ROOT)
        RAW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        results = run_all_collections(output_dir=str(RAW_OUTPUT_DIR))
        if all(v == "failed" for v in results.values()):
            raise RuntimeError(f"전체 수집 실패: {results}")

        logger.info("수집 결과: %s", results)
        return results

    @task(execution_timeout=timedelta(hours=2))
    def rebuild_index(collect_result: dict) -> dict:  # noqa: ARG001
        """GCS 원본 → 청킹 → 임베딩 → FAISS 인덱스 빌드 → GCS 업로드."""
        from src.ingestion.pipeline import build_index_from_gcs

        result = build_index_from_gcs()
        if not result.get("index_built"):
            raise RuntimeError(f"인덱스 빌드 실패: {result}")

        logger.info(
            "인덱스 빌드 완료: %d문서, %d청크, dim=%d",
            result["documents"],
            result["chunks"],
            result.get("embedding_dim", 0),
        )
        return result

    @task()
    def restart_api(index_result: dict) -> str:  # noqa: ARG001
        """Cloud Run API 서비스 재시작 — 새 인덱스 로드."""
        return restart_cloud_run_service(
            service="rag-youth-policy-api",
            region="asia-northeast3",
        )

    @task()
    def sync_to_aws(index_result: dict) -> dict:  # noqa: ARG001
        """AWS DataSync로 GCS → S3 인덱스 동기화. 실패 시 soft failure."""
        from utils.datasync_trigger import start_datasync_task

        try:
            return start_datasync_task()
        except Exception:
            logger.exception("AWS DataSync 실패 — GCS 인덱스는 정상, AWS 수동 동기화 필요")
            return {"status": "FAILED", "task_execution_arn": "", "duration_seconds": 0}

    @task()
    def deploy_aws_api(datasync_result: dict, index_result: dict) -> str:
        """DataSync 완료 후 AWS API 서버 재배포 트리거. DataSync 실패 시 건너뜀."""
        from utils.github_dispatch import trigger_repository_dispatch

        if datasync_result.get("status") != "SUCCESS":
            logger.warning("DataSync 미완료, AWS 배포 건너뜀: %s", datasync_result)
            return "skipped:datasync_not_complete"

        try:
            return trigger_repository_dispatch(
                owner=_AWS_DEPLOY_OWNER,
                repo=_AWS_DEPLOY_REPO,
                event_type="deploy-api",
                client_payload={
                    "source": "airflow:collect_and_index",
                    "chunks": index_result.get("chunks", 0),
                    "embedding_dim": index_result.get("embedding_dim", 0),
                    "gcs_bucket": "rag-qna-eval-data",
                    "gcs_prefix": "index",
                },
            )
        except Exception:
            logger.exception("AWS 배포 트리거 실패 — AWS 수동 배포 필요")
            return "failed:github_dispatch_error"

    collected = collect_all_sources()
    indexed = rebuild_index(collected)

    # GCP: Cloud Run 재시작 (기존)
    restart_api(indexed)

    # AWS: DataSync 동기화 → 배포 트리거 (신규, soft failure)
    synced = sync_to_aws(indexed)
    deploy_aws_api(synced, indexed)


collect_and_index()
