"""Cloud Run 운영 보조 유틸리티.

Phase 6 배포에서는 컨테이너 이미지에 FAISS 인덱스를 굽지 않고, 기동 시 GCS의
`index/faiss.index`, `index/metadata.json`을 로컬 디스크로 내려받아 로드한다.
로컬 개발/테스트 환경에서는 이미 파일이 있으면 다운로드를 건너뛰므로 GCP 인증이
없어도 앱을 실행할 수 있다.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

_INDEX_FILES = ("faiss.index", "metadata.json")


def ensure_index_files(index_dir: Path) -> dict[str, object]:
    """FAISS 인덱스 파일을 준비한다.

    Returns:
        운영/헬스체크에서 사용할 수 있는 상태 dict.
    """
    index_dir = Path(index_dir)
    local_files = [index_dir / filename for filename in _INDEX_FILES]
    have_all_files = all(path.exists() for path in local_files)

    if have_all_files and not settings.force_gcs_index_download:
        return {
            "source": "local",
            "downloaded": False,
            "available": True,
            "files": {path.name: str(path) for path in local_files},
        }

    if not settings.download_index_from_gcs:
        return {
            "source": "local",
            "downloaded": False,
            "available": have_all_files,
            "files": {path.name: str(path) for path in local_files if path.exists()},
        }

    try:
        from src.ingestion.gcs_client import GCSClient

        index_dir.mkdir(parents=True, exist_ok=True)
        gcs = GCSClient()
        prefix = settings.index_gcs_prefix.strip("/")
        downloaded: dict[str, str] = {}
        for filename in _INDEX_FILES:
            gcs_path = f"{prefix}/{filename}" if prefix else filename
            local_path = index_dir / filename
            gcs.download_file(gcs_path, local_path)
            downloaded[filename] = f"gs://{settings.gcs_bucket}/{gcs_path}"

        logger.info("FAISS index downloaded from GCS: %s", downloaded)
        return {
            "source": "gcs",
            "downloaded": True,
            "available": True,
            "files": downloaded,
        }
    except Exception as exc:
        logger.warning("GCS index download skipped/failed: %s", exc)
        return {
            "source": "gcs",
            "downloaded": False,
            "available": all(path.exists() for path in local_files),
            "error": str(exc),
            "files": {path.name: str(path) for path in local_files if path.exists()},
        }


def get_index_last_updated(index_dir: Path) -> str | None:
    """metadata.json 기준 인덱스 최종 수정 시각(UTC ISO)을 반환."""
    from datetime import datetime, timezone

    metadata_path = Path(index_dir) / "metadata.json"
    if not metadata_path.exists():
        return None
    return datetime.fromtimestamp(metadata_path.stat().st_mtime, tz=timezone.utc).isoformat()


def check_gcs_access() -> tuple[bool | None, str | None]:
    """GCS 접근 가능 여부를 가볍게 확인한다. 비프로덕션에서는 (None, None)."""
    if settings.environment != "production" and os.getenv("CHECK_GCS_HEALTH", "").lower() not in {"1", "true", "yes"}:
        return None, None
    try:
        from src.ingestion.gcs_client import GCSClient

        prefix = settings.index_gcs_prefix.strip("/")
        gcs_path = f"{prefix}/metadata.json" if prefix else "metadata.json"
        return GCSClient().exists(gcs_path), None
    except Exception as exc:
        return False, str(exc)
