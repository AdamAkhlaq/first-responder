"""Tests for the telemetry data models the tool layer returns."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from first_responder.schema.telemetry import (
    DeployEvent,
    LogEntry,
    MetricSeries,
    RunbookChunk,
    Span,
    Trace,
)
from first_responder.schema.time import TimeRange

# --- representative instances -------------------------------------------------


def test_log_entry_representative() -> None:
    entry = LogEntry(
        timestamp=12,
        service="checkout",
        level="error",
        message="upstream request timed out",
        fields={"status": 504, "downstream": "payments"},
        request_id="req-abc",
    )
    assert entry.level == "error"
    assert entry.fields["status"] == 504
    assert entry.request_id == "req-abc"


def test_log_entry_optional_fields_default() -> None:
    entry = LogEntry(timestamp=0, service="checkout", level="info", message="ok")
    assert entry.fields == {}
    assert entry.request_id is None


def test_metric_series_representative() -> None:
    series = MetricSeries(
        service="payments",
        metric="latency_ms",
        unit="ms",
        baseline=40.0,
        anomaly_window=TimeRange(start=0, end=120),
        p50=210.0,
        p95=880.0,
        p99=1500.0,
    )
    # The summary captures a spike: tail percentiles sit well above baseline.
    assert series.p99 > series.baseline
    assert series.anomaly_window.duration == 120


def test_span_and_trace_representative() -> None:
    root = Span(
        span_id="s1",
        parent_span_id=None,
        service="checkout",
        operation="POST /checkout",
        start=0,
        end=900,
        status="error",
    )
    child = Span(
        span_id="s2",
        parent_span_id="s1",
        service="payments",
        operation="charge",
        start=10,
        end=890,
        status="ok",
    )
    trace = Trace(request_id="req-abc", spans=[root, child])

    assert child.duration == 880
    # The downstream hop is reachable by matching parent_span_id to the root's id.
    downstream = [s for s in trace.spans if s.parent_span_id == root.span_id]
    assert downstream == [child]


def test_deploy_event_representative() -> None:
    deploy = DeployEvent(
        timestamp=0,
        service="checkout",
        version="v2.4.1",
        summary="swap payment client to async pool",
    )
    assert deploy.version == "v2.4.1"
    assert deploy.timestamp == 0


def test_runbook_chunk_representative() -> None:
    chunk = RunbookChunk(
        id="rb-latency-01",
        title="Diagnosing downstream latency",
        source="runbooks/latency.md",
        text="When a service slows, check its downstream dependencies first.",
    )
    # Relevance is unset until a search scores it against a query.
    assert chunk.relevance is None
    assert chunk.model_copy(update={"relevance": 0.91}).relevance == 0.91


# --- required-field / contract validation -------------------------------------


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (LogEntry, {"service": "a", "level": "info", "message": "m"}),  # no timestamp
        (DeployEvent, {"timestamp": 0, "service": "a", "version": "v1"}),  # no summary
        (RunbookChunk, {"id": "x", "title": "t", "source": "s"}),  # no text
    ],
)
def test_missing_required_field_rejected(model: type, kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        model(**kwargs)


def test_log_level_must_be_known() -> None:
    with pytest.raises(ValidationError):
        LogEntry(timestamp=0, service="a", level="trace", message="m")  # type: ignore[arg-type]


def test_metric_series_rejects_unordered_percentiles() -> None:
    with pytest.raises(ValidationError):
        MetricSeries(
            service="a",
            metric="latency_ms",
            unit="ms",
            baseline=40.0,
            anomaly_window=TimeRange(start=0, end=60),
            p50=900.0,
            p95=200.0,  # below p50 — impossible for percentiles
            p99=1500.0,
        )


def test_span_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        Span(
            span_id="s1",
            parent_span_id=None,
            service="a",
            operation="op",
            start=100,
            end=50,
            status="ok",
        )


def test_telemetry_models_are_immutable() -> None:
    deploy = DeployEvent(timestamp=0, service="a", version="v1", summary="s")
    with pytest.raises(ValidationError):
        deploy.version = "v2"
