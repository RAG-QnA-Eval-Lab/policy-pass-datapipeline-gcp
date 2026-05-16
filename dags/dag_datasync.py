"""AWS DataSync 전용 DAG — 기존 GCS FAISS 인덱스를 AWS S3로 동기화.

스케줄: 수동 트리거 전용 (collect_and_index DAG 꺼놓은 상태에서 독립 실행 가능).
흐름: DataSync 동기화 → AWS API 배포 트리거
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from utils.notifications import on_failure_callback

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "rag-pipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "on_failure_callback": on_failure_callback,
}

_AWS_DEPLOY_OWNER = os.environ.get("AWS_DEPLOY_OWNER", "RAG-QnA-Eval-Lab")
_AWS_DEPLOY_REPO = os.environ.get("AWS_DEPLOY_REPO", "policy-pass-infra-aws")


@dag(
    dag_id="datasync_to_aws",
    default_args=DEFAULT_ARGS,
    description="GCS FAISS 인덱스 → AWS S3 동기화 + AWS API 재배포 (수동 트리거)",
    schedule=None,
    start_date=pendulum.datetime(2026, 4, 25, tz="Asia/Seoul"),
    catchup=False,
    tags=["aws", "datasync", "manual"],
    max_active_runs=1,
)
def datasync_to_aws():
    @task(execution_timeout=timedelta(minutes=45))
    def sync_index() -> dict:
        """AWS DataSync로 GCS → S3 인덱스 동기화."""
        from utils.datasync_trigger import start_datasync_task

        return start_datasync_task()

    @task()
    def deploy_aws_api(datasync_result: dict) -> str:
        """DataSync 완료 후 AWS API 서버 재배포 트리거."""
        from utils.github_dispatch import trigger_repository_dispatch

        if datasync_result.get("status") != "SUCCESS":
            logger.warning("DataSync 미완료, AWS 배포 건너뜀: %s", datasync_result)
            return "skipped:datasync_not_complete"

        return trigger_repository_dispatch(
            owner=_AWS_DEPLOY_OWNER,
            repo=_AWS_DEPLOY_REPO,
            event_type="deploy-api",
            client_payload={
                "source": "airflow:datasync_to_aws",
                "gcs_bucket": "rag-qna-eval-data",
                "gcs_prefix": "index",
            },
        )

    synced = sync_index()
    deploy_aws_api(synced)


datasync_to_aws()
