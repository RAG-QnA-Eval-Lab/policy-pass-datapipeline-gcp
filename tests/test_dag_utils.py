"""DAG 유틸리티 테스트 — github_dispatch, datasync_trigger, cloud_run (dags/utils/)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# dags/utils/는 패키지가 아니라 Airflow DAG 경로에 있는 모듈이므로
# 테스트에서 import할 수 있도록 sys.path에 dags/ 를 추가한다.
_DAGS_DIR = str(Path(__file__).resolve().parent.parent / "dags")
if _DAGS_DIR not in sys.path:
    sys.path.insert(0, _DAGS_DIR)


def _import_github_dispatch() -> ModuleType:
    """github_dispatch 모듈을 (재)임포트한다."""
    return importlib.import_module("utils.github_dispatch")


def _import_datasync_trigger(mock_boto3: MagicMock | None = None) -> ModuleType:
    """datasync_trigger 모듈을 임포트한다. boto3가 없으면 mock으로 주입."""
    if "boto3" not in sys.modules:
        sys.modules["boto3"] = mock_boto3 or MagicMock()
    mod = importlib.import_module("utils.datasync_trigger")
    return mod


# ── github_dispatch.py ───────────────────────────────────────


class TestTriggerRepositoryDispatch:
    def _call(self, mock_post: MagicMock, pat: str = "ghp_test_token_123", **kwargs):
        mod = _import_github_dispatch()
        with patch.object(mod, "_GITHUB_PAT", pat), patch.object(mod, "requests") as mock_req:
            mock_req.post = mock_post
            return mod.trigger_repository_dispatch(**kwargs)

    def test_success_204(self) -> None:
        mock_post = MagicMock(return_value=MagicMock(status_code=204))

        result = self._call(
            mock_post,
            owner="TestOwner",
            repo="test-repo",
            event_type="deploy-api",
            client_payload={"version": "1.0"},
        )

        assert result == "dispatched:TestOwner/test-repo:deploy-api"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["event_type"] == "deploy-api"
        assert call_kwargs.kwargs["json"]["client_payload"]["version"] == "1.0"
        assert "Bearer ghp_test_token_123" in call_kwargs.kwargs["headers"]["Authorization"]

    def test_failure_non_204(self) -> None:
        mock_post = MagicMock(return_value=MagicMock(status_code=404, text="Not Found"))

        with pytest.raises(RuntimeError, match="GitHub API 실패"):
            self._call(mock_post, owner="owner", repo="repo", event_type="deploy-api")

    def test_missing_token_raises(self) -> None:
        mod = _import_github_dispatch()
        with patch.object(mod, "_GITHUB_PAT", ""):
            with pytest.raises(ValueError, match="GITHUB_PAT"):
                mod.trigger_repository_dispatch("owner", "repo", "deploy-api")

    def test_invalid_owner_raises(self) -> None:
        mod = _import_github_dispatch()
        with patch.object(mod, "_GITHUB_PAT", "ghp_test"):
            with pytest.raises(ValueError, match="owner"):
                mod.trigger_repository_dispatch("bad/owner", "repo", "deploy-api")

    def test_invalid_event_type_raises(self) -> None:
        mod = _import_github_dispatch()
        with patch.object(mod, "_GITHUB_PAT", "ghp_test"):
            with pytest.raises(ValueError, match="event_type"):
                mod.trigger_repository_dispatch("owner", "repo", "bad event type")

    def test_no_client_payload(self) -> None:
        mock_post = MagicMock(return_value=MagicMock(status_code=204))

        result = self._call(mock_post, owner="owner", repo="repo", event_type="deploy-api")

        assert result == "dispatched:owner/repo:deploy-api"
        body = mock_post.call_args.kwargs["json"]
        assert "client_payload" not in body


# ── datasync_trigger.py ──────────────────────────────────────


class TestStartDatasyncTask:
    _VALID_ARN = "arn:aws:datasync:ap-northeast-2:355206939988:task/task-0981d5902107c4cb5"
    _EXEC_ARN = f"{_VALID_ARN}/execution/exec-abc123"

    def _get_module(self) -> ModuleType:
        mock_boto3 = MagicMock()
        return _import_datasync_trigger(mock_boto3)

    def test_success_immediate(self) -> None:
        mod = self._get_module()
        mock_client = MagicMock()
        mock_client.start_task_execution.return_value = {"TaskExecutionArn": self._EXEC_ARN}
        mock_client.describe_task_execution.return_value = {"Status": "SUCCESS"}

        with patch.object(mod, "boto3") as mock_b3:
            mock_b3.client.return_value = mock_client
            result = mod.start_datasync_task(task_arn=self._VALID_ARN, poll_timeout=60)

        assert result["status"] == "SUCCESS"
        assert result["task_execution_arn"] == self._EXEC_ARN
        assert result["duration_seconds"] >= 0

    def test_success_after_polling(self) -> None:
        mod = self._get_module()
        mock_client = MagicMock()
        mock_client.start_task_execution.return_value = {"TaskExecutionArn": self._EXEC_ARN}
        mock_client.describe_task_execution.side_effect = [
            {"Status": "LAUNCHING"},
            {"Status": "TRANSFERRING"},
            {"Status": "VERIFYING"},
            {"Status": "SUCCESS"},
        ]

        with (
            patch.object(mod, "boto3") as mock_b3,
            patch.object(mod, "time") as mock_time,
        ):
            mock_b3.client.return_value = mock_client
            mock_time.monotonic.side_effect = [0, 10, 10, 20, 20, 30, 30, 40, 40]
            mock_time.sleep = MagicMock()

            result = mod.start_datasync_task(task_arn=self._VALID_ARN, poll_timeout=300)

        assert result["status"] == "SUCCESS"
        assert mock_client.describe_task_execution.call_count == 4

    def test_error_status_raises(self) -> None:
        mod = self._get_module()
        mock_client = MagicMock()
        mock_client.start_task_execution.return_value = {"TaskExecutionArn": self._EXEC_ARN}
        mock_client.describe_task_execution.return_value = {
            "Status": "ERROR",
            "Result": {"ErrorDetail": "Source location unavailable"},
        }

        with (
            patch.object(mod, "boto3") as mock_b3,
            patch.object(mod, "time") as mock_time,
        ):
            mock_b3.client.return_value = mock_client
            mock_time.monotonic.side_effect = [0, 5, 5]
            mock_time.sleep = MagicMock()

            with pytest.raises(RuntimeError, match="DataSync 실패"):
                mod.start_datasync_task(task_arn=self._VALID_ARN, poll_timeout=60)

    def test_empty_arn_raises(self) -> None:
        mod = self._get_module()
        with pytest.raises(ValueError, match="AWS_DATASYNC_TASK_ARN"):
            mod.start_datasync_task(task_arn="")

    def test_invalid_arn_format_raises(self) -> None:
        mod = self._get_module()
        with pytest.raises(ValueError, match="잘못된 DataSync Task ARN"):
            mod.start_datasync_task(task_arn="not-a-valid-arn")

    def test_timeout_raises(self) -> None:
        mod = self._get_module()
        mock_client = MagicMock()
        mock_client.start_task_execution.return_value = {"TaskExecutionArn": self._EXEC_ARN}
        mock_client.describe_task_execution.return_value = {"Status": "TRANSFERRING"}

        with (
            patch.object(mod, "boto3") as mock_b3,
            patch.object(mod, "time") as mock_time,
        ):
            mock_b3.client.return_value = mock_client
            mock_time.monotonic.side_effect = [0, 5, 5, 100]
            mock_time.sleep = MagicMock()

            with pytest.raises(RuntimeError, match="타임아웃"):
                mod.start_datasync_task(task_arn=self._VALID_ARN, poll_timeout=60)


# ── cloud_run.py (dags/utils/) ───────────────────────────────


class TestRestartCloudRunService:
    @patch("utils.cloud_run.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        from utils.cloud_run import restart_cloud_run_service

        mock_run.return_value = MagicMock(returncode=0)

        result = restart_cloud_run_service(service="test-api", region="asia-northeast3")

        assert result == "restarted:test-api"
        assert mock_run.call_count == 2

    def test_invalid_service_name_raises(self) -> None:
        from utils.cloud_run import restart_cloud_run_service

        with pytest.raises(ValueError, match="Invalid Cloud Run service name"):
            restart_cloud_run_service(service="INVALID_NAME!")
