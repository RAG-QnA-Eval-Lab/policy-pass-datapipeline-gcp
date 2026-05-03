"""Cloud Run 서비스 관리 유틸리티."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "rag-qna-eval")
_SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{0,62}$")


def restart_cloud_run_service(
    service: str,
    region: str = "asia-northeast3",
    project: str | None = None,
) -> str:
    """Cloud Run 서비스에 새 revision 배포 (인덱스 재로드).

    Cloud Run은 새 revision이 뜨면 GCS에서 최신 인덱스를 다운로드한다.
    ``gcloud run services update`` 로 새 revision을 트리거한다.
    """
    if project is None:
        project = _DEFAULT_PROJECT

    if not _SERVICE_NAME_RE.match(service):
        raise ValueError(f"Invalid Cloud Run service name: {service!r}")

    cmd = [
        "gcloud",
        "run",
        "services",
        "update",
        service,
        "--region",
        region,
        "--project",
        project,
        "--no-traffic",
        "--update-env-vars",
        f"FORCE_RESTART={_timestamp()}",
    ]

    env = os.environ.copy()
    env.setdefault("CLOUDSDK_CONFIG", os.path.join(env.get("HOME", "/opt/airflow"), ".config", "gcloud"))

    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True, env=env)
        logger.info("Cloud Run 재시작 성공: %s (%s)", service, region)

        migrate_cmd = [
            "gcloud",
            "run",
            "services",
            "update-traffic",
            service,
            "--region",
            region,
            "--project",
            project,
            "--to-latest",
        ]
        subprocess.run(migrate_cmd, capture_output=True, text=True, timeout=60, check=True, env=env)
        logger.info("트래픽 전환 완료: %s", service)

        return f"restarted:{service}"
    except subprocess.CalledProcessError as e:
        logger.error("Cloud Run 재시작 실패: %s\nstderr: %s", service, e.stderr)
        raise


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
