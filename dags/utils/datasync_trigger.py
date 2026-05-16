"""AWS DataSync 태스크 실행 유틸리티.

GCS → S3 인덱스 동기화를 위한 DataSync 태스크를 시작하고 완료를 대기한다.
환경변수: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DATASYNC_TASK_ARN.

필요 IAM 권한:
  - datasync:StartTaskExecution (해당 Task ARN)
  - datasync:DescribeTaskExecution (해당 Task ARN/execution/*)
"""

from __future__ import annotations

import logging
import os
import re
import time

import boto3

logger = logging.getLogger(__name__)

_DATASYNC_TASK_ARN = os.environ.get("AWS_DATASYNC_TASK_ARN", "")
_DATASYNC_REGION = os.environ.get("AWS_DATASYNC_REGION", "ap-northeast-2")
_ARN_RE = re.compile(r"^arn:aws:datasync:[a-z0-9-]+:\d{12}:task/task-[a-f0-9]+$")

_POLL_INITIAL_INTERVAL = 10
_POLL_MAX_INTERVAL = 60
_POLL_TIMEOUT = 1800

_TERMINAL_STATUSES = frozenset({"SUCCESS", "ERROR"})
_IN_PROGRESS_STATUSES = frozenset({"QUEUED", "LAUNCHING", "PREPARING", "TRANSFERRING", "VERIFYING"})


def start_datasync_task(
    task_arn: str | None = None,
    poll_timeout: int = _POLL_TIMEOUT,
) -> dict:
    """DataSync 태스크를 시작하고 완료까지 polling한다.

    Args:
        task_arn: DataSync Task ARN. None이면 환경변수에서 읽는다.
        poll_timeout: 최대 대기 시간(초). 기본 1800초(30분).

    Returns:
        {"task_execution_arn": str, "status": str, "duration_seconds": float} dict.

    Raises:
        ValueError: ARN이 비어있거나 형식이 잘못된 경우.
        RuntimeError: DataSync 실행 실패 또는 타임아웃.
    """
    arn = task_arn or _DATASYNC_TASK_ARN
    if not arn:
        raise ValueError("AWS_DATASYNC_TASK_ARN 환경변수가 설정되지 않음")
    if not _ARN_RE.match(arn):
        raise ValueError(f"잘못된 DataSync Task ARN 형식: {arn!r}")

    client = boto3.client("datasync", region_name=_DATASYNC_REGION)

    start_time = time.monotonic()
    resp = client.start_task_execution(TaskArn=arn)
    execution_arn = resp["TaskExecutionArn"]
    logger.info("DataSync 실행 시작: %s", execution_arn)

    interval = _POLL_INITIAL_INTERVAL
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > poll_timeout:
            raise RuntimeError(f"DataSync 타임아웃 ({poll_timeout}초 초과): {execution_arn}")

        time.sleep(interval)

        desc = client.describe_task_execution(TaskExecutionArn=execution_arn)
        status = desc["Status"]
        logger.info("DataSync 상태: %s (%.0f초 경과)", status, elapsed)

        if status == "SUCCESS":
            duration = time.monotonic() - start_time
            logger.info("DataSync 완료: %.0f초 소요", duration)
            return {
                "task_execution_arn": execution_arn,
                "status": "SUCCESS",
                "duration_seconds": round(duration, 1),
            }

        if status == "ERROR":
            error_detail = desc.get("Result", {}).get("ErrorDetail", "상세 정보 없음")
            raise RuntimeError(f"DataSync 실패: {execution_arn} — {error_detail}")

        if status not in _IN_PROGRESS_STATUSES:
            raise RuntimeError(f"DataSync 예상치 못한 상태: {status}")

        interval = min(interval * 1.5, _POLL_MAX_INTERVAL)
