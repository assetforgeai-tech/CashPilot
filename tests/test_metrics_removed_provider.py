from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app import database, exchange_rates, metrics


class _Metric:
    def __init__(self) -> None:
        self.labels_seen: list[dict[str, str]] = []
        self.values: list[float] = []
        self.inc_count = 0
        self.clear_count = 0

    def clear(self) -> None:
        self.clear_count += 1
        self.labels_seen.clear()
        self.values.clear()

    def labels(self, **labels: str) -> _Metric:
        self.labels_seen.append(labels)
        return self

    def set(self, value: float) -> None:
        self.values.append(value)

    def inc(self, amount: float = 1) -> None:
        self.inc_count += amount


def _metric_store() -> dict[str, _Metric]:
    names = (
        "containers_total",
        "container_info",
        "container_cpu_percent",
        "container_memory_mb",
        "worker_last_heartbeat_seconds",
        "worker_docker_available",
        "worker_containers_count",
        "workers_total",
        "earnings_balance",
        "earnings_balance_usd",
        "earnings_total_usd",
        "services_deployed_total",
        "services_available_total",
        "health_score",
        "health_uptime_percent",
        "collection_errors_total",
        "container_lifecycle_total",
    )
    return {name: _Metric() for name in names}


def test_prometheus_refresh_hides_legacy_grass_rows_and_containers():
    async def run() -> None:
        store = _metric_store()
        old_metrics = metrics._metrics
        old_last_refresh = metrics._last_refresh
        metrics._metrics = store
        metrics._last_refresh = 0
        try:
            workers = [
                {
                    "name": "worker-a",
                    "status": "online",
                    "last_heartbeat": None,
                    "system_info": json.dumps({"docker_available": True}),
                    "containers": json.dumps(
                        [
                            {"slug": "grass", "status": "running", "cpu_percent": 1, "memory_mb": 2},
                            {"slug": "earnfm", "status": "running", "cpu_percent": 3, "memory_mb": 4},
                        ]
                    ),
                }
            ]
            earnings = [
                {"platform": "grass", "balance": 10.0, "currency": "USD"},
                {"platform": "earnfm", "balance": 2.0, "currency": "USD"},
            ]
            deployments = [{"slug": "grass"}, {"slug": "earnfm"}]
            scores = [{"slug": "grass", "score": 10}, {"slug": "earnfm", "score": 90}]

            with (
                patch.object(database, "list_workers", new_callable=AsyncMock, return_value=workers),
                patch.object(database, "get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
                patch.object(database, "get_deployments", new_callable=AsyncMock, return_value=deployments),
                patch.object(database, "get_health_scores", new_callable=AsyncMock, return_value=scores),
                patch.object(exchange_rates, "to_usd", side_effect=lambda balance, currency: balance),
            ):
                await metrics._refresh_gauges()

            assert {row["platform"] for row in store["earnings_balance"].labels_seen} == {"earnfm"}
            assert {row["service"] for row in store["container_info"].labels_seen} == {"earnfm"}
            assert {row["service"] for row in store["health_score"].labels_seen} == {"earnfm"}
            assert store["worker_containers_count"].values == [1]
            assert store["services_deployed_total"].values == [1]
            assert store["earnings_total_usd"].values == [2.0]
        finally:
            metrics._metrics = old_metrics
            metrics._last_refresh = old_last_refresh

    asyncio.run(run())


def test_metric_hooks_ignore_retired_grass_but_keep_unknown_and_active_slugs():
    store = _metric_store()
    old_metrics = metrics._metrics
    metrics._metrics = store
    try:
        with patch.object(metrics, "METRICS_ENABLED", True):
            metrics.record_collection_error("grass")
            metrics.record_collection_error("earnfm")
            metrics.record_collection_error("integration-fixture")
            metrics.record_container_lifecycle("deploy", "grass")
            metrics.record_container_lifecycle("deploy", "earnfm")
            metrics.record_container_lifecycle("deploy", "integration-fixture")

        assert store["collection_errors_total"].labels_seen == [
            {"platform": "earnfm"},
            {"platform": "integration-fixture"},
        ]
        assert store["container_lifecycle_total"].labels_seen == [
            {"action": "deploy", "service": "earnfm"},
            {"action": "deploy", "service": "integration-fixture"},
        ]
    finally:
        metrics._metrics = old_metrics
