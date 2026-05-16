"""GCP Cloud Monitoring 커스텀 메트릭 전송.

운영 환경에서 `ENABLE_CLOUD_MONITORING=true`일 때만 실제 전송한다. 로컬 테스트와
개발 환경에서는 no-op으로 동작해 GCP 인증/의존성 없이도 안전하다.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from config.settings import settings

logger = logging.getLogger(__name__)

_METRIC_PREFIX = "custom.googleapis.com/rag"


class MonitoringClient:
    """Cloud Monitoring lazy client wrapper."""

    def __init__(self) -> None:
        self.enabled = bool(settings.enable_cloud_monitoring)
        self._client: Any | None = None
        self._project_name = f"projects/{settings.gcp_project}"

    @property
    def client(self) -> Any | None:
        if not self.enabled:
            return None
        if self._client is None:
            try:
                from google.cloud import monitoring_v3

                self._client = monitoring_v3.MetricServiceClient()
            except Exception as exc:
                logger.warning("Cloud Monitoring client unavailable: %s", exc)
                return None
        return self._client

    def write_metric(self, name: str, value: float | int, labels: dict[str, str] | None = None) -> None:
        """단일 GAUGE 커스텀 메트릭을 best-effort로 전송."""
        client = self.client
        if client is None:
            return

        try:
            from google.cloud import monitoring_v3

            series = monitoring_v3.TimeSeries()
            series.metric.type = f"{_METRIC_PREFIX}/{name}"
            for key, label_value in (labels or {}).items():
                if label_value is not None:
                    series.metric.labels[key] = str(label_value)
            series.resource.type = "global"

            now = time.time()
            seconds = int(now)
            nanos = int((now - seconds) * 10**9)
            interval = monitoring_v3.TimeInterval(
                {"end_time": {"seconds": seconds, "nanos": nanos}},
            )
            point = monitoring_v3.Point(
                {
                    "interval": interval,
                    "value": {"double_value": float(value)},
                }
            )
            series.points = [point]
            client.create_time_series(name=self._project_name, time_series=[series])
        except Exception as exc:
            # 요청 경로를 막지 않기 위해 모든 오류를 삼킨다.
            logger.debug("Cloud Monitoring metric write failed: %s", exc)

    def record_request(self, path: str, method: str, status: int, latency_ms: float) -> None:
        self.write_metric(
            "total_latency_ms",
            latency_ms,
            {"path": path, "method": method, "status": str(status)},
        )
        if status >= 400:
            self.write_metric("error_count", 1, {"path": path, "method": method, "status": str(status)})

    def record_generation(
        self,
        *,
        model: str,
        strategy: str,
        retrieval_latency_ms: float,
        generation_latency_ms: float,
        tokens_used: int,
        estimated_cost_usd: float,
    ) -> None:
        labels = {"model": model, "strategy": strategy}
        self.write_metric("retrieval_latency_ms", retrieval_latency_ms, labels)
        self.write_metric("generation_latency_ms", generation_latency_ms, labels)
        self.write_metric("tokens_used", tokens_used, labels)
        self.write_metric("estimated_cost_usd", estimated_cost_usd, labels)


@lru_cache
def get_monitoring_client() -> MonitoringClient:
    return MonitoringClient()
