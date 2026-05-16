"""GitHub repository_dispatch 트리거 유틸리티.

Airflow DAG에서 GitHub Actions 워크플로를 원격 트리거할 때 사용.
환경변수 GITHUB_PAT에 repo scope Personal Access Token 필요.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

_GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
_REPO_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def trigger_repository_dispatch(
    owner: str,
    repo: str,
    event_type: str,
    client_payload: dict[str, Any] | None = None,
) -> str:
    """GitHub repository_dispatch 이벤트를 트리거한다.

    Args:
        owner: GitHub 사용자/조직 이름.
        repo: 리포지토리 이름.
        event_type: 워크플로에서 수신할 이벤트 타입 (예: "deploy-api").
        client_payload: 워크플로에 전달할 추가 데이터.

    Returns:
        "dispatched:{owner}/{repo}:{event_type}" 형태 문자열.

    Raises:
        ValueError: owner/repo/event_type 형식이 잘못된 경우.
        RuntimeError: GitHub API 호출 실패.
    """
    token = _GITHUB_PAT
    if not token:
        raise ValueError("GITHUB_PAT 환경변수가 설정되지 않음")

    if not _REPO_NAME_RE.match(owner):
        raise ValueError(f"잘못된 owner 형식: {owner!r}")
    if not _REPO_NAME_RE.match(repo):
        raise ValueError(f"잘못된 repo 형식: {repo!r}")
    if not _REPO_NAME_RE.match(event_type):
        raise ValueError(f"잘못된 event_type 형식: {event_type!r}")

    url = f"https://api.github.com/repos/{owner}/{repo}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body: dict[str, Any] = {"event_type": event_type}
    if client_payload:
        body["client_payload"] = client_payload

    resp = requests.post(url, json=body, headers=headers, timeout=30)

    if resp.status_code == 204:
        logger.info("repository_dispatch 성공: %s/%s event=%s", owner, repo, event_type)
        return f"dispatched:{owner}/{repo}:{event_type}"

    logger.error(
        "repository_dispatch 실패: %s/%s status=%d body=%s",
        owner,
        repo,
        resp.status_code,
        resp.text[:500],
    )
    raise RuntimeError(f"GitHub API 실패 (HTTP {resp.status_code}): {resp.text[:200]}")
