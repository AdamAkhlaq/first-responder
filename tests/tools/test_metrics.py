"""Tests for query_metrics: the spike survives summarisation; flat/empty stay total.

These pin the contract that matters for ADR-002 — the summary must *preserve the
signal*. A real incident (bad_deploy's error-rate spike, cascading_timeout's
downstream latency spike) has to come back as p95/p99 standing well above the
baseline, while a flat series, an out-of-range window, and an unknown metric must
all summarise deterministically without an exception or a NaN — and never as raw
points.
"""

from __future__ import annotations

import math

import pytest

from first_responder.schema.telemetry import MetricSeries
from first_responder.schema.time import TimeRange
from first_responder.simulator.scenarios import bad_deploy as bd
from first_responder.simulator.scenarios import cascading_timeout as ct
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult
from first_responder.tools.metrics import query_metrics
from first_responder.tools.registry import ToolCall, dispatch

SEED = 7
T0 = bd.T0
_INCIDENT = TimeRange.since(T0, 300)  # [0, 300): the spiked anomaly window
_PRE = TimeRange(start=T0 - 300, end=T0)  # [-300, 0): the calm baseline window
_FAR_BEFORE = TimeRange(start=T0 - 1200, end=T0 - 600)  # no series overlaps this


@pytest.fixture
def bad_deploy_store() -> TelemetryStore:
    store, _ = bd.BAD_DEPLOY.activate(SEED)
    return store


@pytest.fixture
def cascading_store() -> TelemetryStore:
    store, _ = ct.CASCADING_TIMEOUT.activate(SEED)
    return store


# --- the spike must survive summarisation (ADR-002's core obligation) ----------


def test_bad_deploy_spike_dominates_baseline(bad_deploy_store: TelemetryStore) -> None:
    result = query_metrics(bad_deploy_store, bd.AFFECTED_SERVICE, "error_rate", _INCIDENT)
    summary = result.data
    assert isinstance(summary, MetricSeries)  # a summary, never a list of raw points
    assert summary.baseline == pytest.approx(bd._BASELINE_ERROR_RATE)
    # The error-rate spike (~30x) lands in the tail, well clear of the baseline.
    assert summary.p95 > summary.baseline * 5
    assert summary.p99 >= summary.p95
    assert "x baseline" in result.finding


def test_cascading_timeout_downstream_latency_spike_shows_up(
    cascading_store: TelemetryStore,
) -> None:
    result = query_metrics(cascading_store, ct.DOWNSTREAM_SERVICE, "latency_ms", _INCIDENT)
    summary = result.data
    assert isinstance(summary, MetricSeries)
    assert summary.baseline == pytest.approx(ct._B_LATENCY_BASELINE_MS)
    # B's latency jumps ~15x at T0 — the cause, plainly visible in the tail.
    assert summary.p95 > summary.baseline * 5
    assert summary.p99 >= summary.p95


def test_pre_incident_window_reads_calm(bad_deploy_store: TelemetryStore) -> None:
    # Querying before the onset summarises the flat baseline segment: no spike.
    result = query_metrics(bad_deploy_store, bd.AFFECTED_SERVICE, "error_rate", _PRE)
    summary = result.data
    assert isinstance(summary, MetricSeries)
    assert summary.p99 < summary.baseline * 2  # calm tail before the incident


# --- flat / empty / unknown: deterministic and total, no exceptions or NaNs ----


def test_flat_series_summarises_without_a_spike(cascading_store: TelemetryStore) -> None:
    # api-gateway CPU is the red herring: flat across the incident (spike == 1.0).
    result = query_metrics(cascading_store, ct.AFFECTED_SERVICE, "cpu_utilization", _INCIDENT)
    summary = result.data
    assert isinstance(summary, MetricSeries)
    assert summary.p99 < summary.baseline * 1.5  # no anomaly to read here
    assert not any(math.isnan(p) for p in (summary.p50, summary.p95, summary.p99))


def test_empty_window_collapses_to_baseline(bad_deploy_store: TelemetryStore) -> None:
    # A window no segment overlaps: known metric, but no data — flat, never a NaN.
    result = query_metrics(bad_deploy_store, bd.AFFECTED_SERVICE, "error_rate", _FAR_BEFORE)
    summary = result.data
    assert isinstance(summary, MetricSeries)
    assert summary.p50 == summary.p95 == summary.p99 == summary.baseline
    assert not math.isnan(summary.p99)


def test_zero_width_window_summarises_without_error(bad_deploy_store: TelemetryStore) -> None:
    point = TimeRange(start=T0, end=T0)  # [0, 0): valid but empty
    result = query_metrics(bad_deploy_store, bd.AFFECTED_SERVICE, "error_rate", point)
    summary = result.data
    assert isinstance(summary, MetricSeries)
    assert summary.p99 == summary.baseline


def test_unknown_metric_returns_structured_finding(bad_deploy_store: TelemetryStore) -> None:
    result = query_metrics(bad_deploy_store, bd.AFFECTED_SERVICE, "no_such_metric", _INCIDENT)
    assert result.data is None
    assert "unknown metric/service" in result.finding


def test_unknown_service_returns_structured_finding(bad_deploy_store: TelemetryStore) -> None:
    result = query_metrics(bad_deploy_store, "no-such-service", "error_rate", _INCIDENT)
    assert result.data is None
    assert "unknown metric/service" in result.finding


# --- registered & dispatchable through the uniform call surface ----------------


def test_query_metrics_is_registered_and_dispatchable(bad_deploy_store: TelemetryStore) -> None:
    call = ToolCall(
        tool="query_metrics",
        args={
            "service": bd.AFFECTED_SERVICE,
            "metric": "error_rate",
            "window": {"start": T0, "end": 300},
        },
    )
    result = dispatch(call, bad_deploy_store)
    assert isinstance(result, ToolResult)
    assert isinstance(result.data, MetricSeries)
    assert result.data.p95 > result.data.baseline * 5
