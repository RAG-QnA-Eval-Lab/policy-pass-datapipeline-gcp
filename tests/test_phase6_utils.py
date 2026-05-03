"""Phase 6 유틸리티 테스트 — cloud_run.py, costs.py, monitoring.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.api.costs import estimate_cost_usd

# ── costs.py ──────────────────────────────────────────────────


class TestEstimateCostUsd:
    def test_known_model(self) -> None:
        cost = estimate_cost_usd("openai/gpt-4o-mini", 1_000_000, 1_000_000)
        assert cost == pytest.approx(0.75)

    def test_unknown_model_returns_zero(self) -> None:
        assert estimate_cost_usd("unknown/model", 500_000, 500_000) == 0.0

    def test_zero_tokens(self) -> None:
        assert estimate_cost_usd("openai/gpt-4o-mini", 0, 0) == 0.0

    def test_prompt_only(self) -> None:
        cost = estimate_cost_usd("openai/gpt-4o-mini", 1_000_000, 0)
        assert cost == pytest.approx(0.15)

    def test_completion_only(self) -> None:
        cost = estimate_cost_usd("openai/gpt-4o-mini", 0, 1_000_000)
        assert cost == pytest.approx(0.60)


# ── cloud_run.py ──────────────────────────────────────────────


class TestEnsureIndexFiles:
    def test_local_files_exist(self, tmp_path: Path) -> None:
        (tmp_path / "faiss.index").write_bytes(b"idx")
        (tmp_path / "metadata.json").write_bytes(b"meta")
        from src.api.cloud_run import ensure_index_files

        with patch("src.api.cloud_run.settings") as mock_settings:
            mock_settings.force_gcs_index_download = False
            result = ensure_index_files(tmp_path)

        assert result["source"] == "local"
        assert result["available"] is True
        assert result["downloaded"] is False

    def test_missing_local_gcs_disabled(self, tmp_path: Path) -> None:
        from src.api.cloud_run import ensure_index_files

        with patch("src.api.cloud_run.settings") as mock_settings:
            mock_settings.force_gcs_index_download = False
            mock_settings.download_index_from_gcs = False
            result = ensure_index_files(tmp_path)

        assert result["available"] is False
        assert result["downloaded"] is False

    def test_gcs_download_success(self, tmp_path: Path) -> None:
        from src.api.cloud_run import ensure_index_files

        mock_gcs = MagicMock()

        with (
            patch("src.api.cloud_run.settings") as mock_settings,
            patch("src.ingestion.gcs_client.GCSClient", return_value=mock_gcs),
        ):
            mock_settings.force_gcs_index_download = False
            mock_settings.download_index_from_gcs = True
            mock_settings.index_gcs_prefix = "index"
            mock_settings.gcs_bucket = "test-bucket"
            result = ensure_index_files(tmp_path)

        assert result["source"] == "gcs"
        assert result["downloaded"] is True
        assert result["available"] is True

    def test_gcs_download_failure(self, tmp_path: Path) -> None:
        from src.api.cloud_run import ensure_index_files

        with (
            patch("src.api.cloud_run.settings") as mock_settings,
            patch("src.ingestion.gcs_client.GCSClient", side_effect=RuntimeError("no creds")),
        ):
            mock_settings.force_gcs_index_download = False
            mock_settings.download_index_from_gcs = True
            mock_settings.index_gcs_prefix = "index"
            mock_settings.gcs_bucket = "test-bucket"
            result = ensure_index_files(tmp_path)

        assert result["source"] == "gcs"
        assert result["downloaded"] is False
        assert "error" in result


class TestCheckGcsAccess:
    def test_disabled_outside_production(self) -> None:
        from src.api.cloud_run import check_gcs_access

        with patch("src.api.cloud_run.settings") as mock_settings:
            mock_settings.environment = "development"
            with patch.dict("os.environ", {}, clear=False):
                ok, err = check_gcs_access()

        assert ok is None
        assert err is None

    def test_production_gcs_accessible(self) -> None:
        from src.api.cloud_run import check_gcs_access

        mock_gcs = MagicMock()
        mock_gcs.exists.return_value = True

        with (
            patch("src.api.cloud_run.settings") as mock_settings,
            patch("src.ingestion.gcs_client.GCSClient", return_value=mock_gcs),
        ):
            mock_settings.environment = "production"
            mock_settings.index_gcs_prefix = "index"
            ok, err = check_gcs_access()

        assert ok is True
        assert err is None

    def test_production_gcs_error(self) -> None:
        from src.api.cloud_run import check_gcs_access

        with (
            patch("src.api.cloud_run.settings") as mock_settings,
            patch("src.ingestion.gcs_client.GCSClient", side_effect=RuntimeError("fail")),
        ):
            mock_settings.environment = "production"
            mock_settings.index_gcs_prefix = "index"
            ok, err = check_gcs_access()

        assert ok is False
        assert err is not None


class TestGetIndexLastUpdated:
    def test_existing_file(self, tmp_path: Path) -> None:
        from src.api.cloud_run import get_index_last_updated

        (tmp_path / "metadata.json").write_bytes(b"data")
        result = get_index_last_updated(tmp_path)
        assert result is not None
        assert "T" in result

    def test_missing_file(self, tmp_path: Path) -> None:
        from src.api.cloud_run import get_index_last_updated

        assert get_index_last_updated(tmp_path) is None


# ── monitoring.py ─────────────────────────────────────────────


class TestMonitoringClient:
    def test_disabled_no_client(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = False
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()
        assert mc.client is None

    def test_write_metric_noop_when_disabled(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = False
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()
            mc.write_metric("test_metric", 42.0)

    def test_record_request_noop(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = False
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()
            mc.record_request("/health", "GET", 200, 5.0)

    def test_record_generation_noop(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = False
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()
            mc.record_generation(
                model="openai/gpt-4o-mini",
                strategy="hybrid",
                retrieval_latency_ms=10.0,
                generation_latency_ms=200.0,
                tokens_used=500,
                estimated_cost_usd=0.001,
            )

    def test_client_init_failure_returns_none(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = True
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()

        with patch.dict("sys.modules", {"google.cloud": None, "google.cloud.monitoring_v3": None}):
            assert mc.client is None

    def test_record_request_error_status(self) -> None:
        with patch("src.api.monitoring.settings") as mock_settings:
            mock_settings.enable_cloud_monitoring = False
            mock_settings.gcp_project = "test"
            from src.api.monitoring import MonitoringClient

            mc = MonitoringClient()
            mc.record_request("/api/v1/generate", "POST", 500, 100.0)
