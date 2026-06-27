"""Tests for the in-memory telemetry store: round-trips, filtering, immutability."""

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
from first_responder.simulator.store import TelemetryStore

# --- fixtures / builders ------------------------------------------------------


def _log(
    service: str, timestamp: int, level: str = "info", request_id: str | None = None
) -> LogEntry:
    return LogEntry(
        timestamp=timestamp,
        service=service,
        level=level,  # type: ignore[arg-type]
        message="m",
        request_id=request_id,
    )


def _series(service: str, metric: str, window: TimeRange) -> MetricSeries:
    return MetricSeries(
        service=service,
        metric=metric,
        unit="ms",
        baseline=40.0,
        anomaly_window=window,
        p50=100.0,
        p95=200.0,
        p99=300.0,
    )


def _trace(request_id: str, services: list[str]) -> Trace:
    spans = [
        Span(
            span_id=f"s{i}",
            parent_span_id=None if i == 0 else "s0",
            service=svc,
            operation="op",
            start=0,
            end=10,
            status="ok",
        )
        for i, svc in enumerate(services)
    ]
    return Trace(request_id=request_id, spans=spans)


@pytest.fixture
def store() -> TelemetryStore:
    return TelemetryStore()


# --- write / read round-trips -------------------------------------------------


def test_logs_round_trip(store: TelemetryStore) -> None:
    entries = [_log("checkout", 0), _log("checkout", 10)]
    store.add_logs(entries)
    assert store.logs_for("checkout") == entries


def test_metric_series_round_trip(store: TelemetryStore) -> None:
    series = _series("payments", "latency_ms", TimeRange(start=0, end=60))
    store.add_metric_series([series])
    assert store.metric_series("payments", "latency_ms") == [series]


def test_traces_round_trip(store: TelemetryStore) -> None:
    trace = _trace("req-1", ["checkout", "payments"])
    store.add_traces([trace])
    assert store.traces(request_id="req-1") == [trace]


def test_deploys_round_trip(store: TelemetryStore) -> None:
    deploy = DeployEvent(timestamp=0, service="checkout", version="v1", summary="s")
    store.add_deploys([deploy])
    assert store.deploys() == [deploy]


def test_runbook_corpus_round_trip(store: TelemetryStore) -> None:
    chunk = RunbookChunk(id="rb-1", title="t", source="s", text="x")
    store.add_runbook_chunks([chunk])
    assert store.runbook_corpus() == [chunk]


def test_writes_accumulate(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0)])
    store.add_logs([_log("checkout", 10)])
    assert len(store.logs_for("checkout")) == 2


# --- service filtering --------------------------------------------------------


def test_logs_filter_by_service(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0), _log("payments", 0)])
    assert [e.service for e in store.logs_for("checkout")] == ["checkout"]


def test_traces_filter_by_service_matches_any_span(store: TelemetryStore) -> None:
    store.add_traces([_trace("req-1", ["checkout", "payments"]), _trace("req-2", ["checkout"])])
    # payments appears only as a downstream span of req-1.
    assert [t.request_id for t in store.traces(service="payments")] == ["req-1"]


def test_metric_series_filter_by_service_and_metric(store: TelemetryStore) -> None:
    window = TimeRange(start=0, end=60)
    store.add_metric_series(
        [
            _series("payments", "latency_ms", window),
            _series("payments", "error_rate", window),
            _series("checkout", "latency_ms", window),
        ]
    )
    got = store.metric_series("payments", "latency_ms")
    assert [(s.service, s.metric) for s in got] == [("payments", "latency_ms")]


# --- window filtering ---------------------------------------------------------


def test_logs_filter_by_window_is_half_open(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", t) for t in (-1, 0, 59, 60)])
    got = store.logs_for("checkout", window=TimeRange(start=0, end=60))
    # [0, 60): 0 and 59 are in, -1 (before) and 60 (end, exclusive) are out.
    assert [e.timestamp for e in got] == [0, 59]


def test_deploys_filter_by_window(store: TelemetryStore) -> None:
    store.add_deploys(
        [
            DeployEvent(timestamp=t, service="checkout", version="v", summary="s")
            for t in (-10, 5, 100)
        ]
    )
    got = store.deploys(window=TimeRange(start=0, end=60))
    assert [d.timestamp for d in got] == [5]


def test_metric_series_filter_by_overlapping_window(store: TelemetryStore) -> None:
    store.add_metric_series(
        [
            _series("payments", "latency_ms", TimeRange(start=0, end=60)),
            _series("payments", "latency_ms", TimeRange(start=120, end=180)),
        ]
    )
    # Query window [30, 90) overlaps the first series only.
    got = store.metric_series("payments", "latency_ms", window=TimeRange(start=30, end=90))
    assert [s.anomaly_window.start for s in got] == [0]


def test_logs_custom_filter_predicate(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0, level="info"), _log("checkout", 1, level="error")])
    got = store.logs_for("checkout", filter=lambda e: e.level == "error")
    assert [e.level for e in got] == ["error"]


# --- empty results ------------------------------------------------------------


def test_readers_return_empty_when_nothing_matches(store: TelemetryStore) -> None:
    assert store.logs_for("nope") == []
    assert store.metric_series("nope", "latency_ms") == []
    assert store.traces(request_id="nope") == []
    assert store.deploys(window=TimeRange(start=0, end=1)) == []
    assert store.runbook_corpus() == []


def test_traces_unfiltered_returns_all(store: TelemetryStore) -> None:
    store.add_traces([_trace("req-1", ["a"]), _trace("req-2", ["b"])])
    assert {t.request_id for t in store.traces()} == {"req-1", "req-2"}


# --- read immutability --------------------------------------------------------


def test_reader_returns_fresh_list_each_call(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0)])
    first = store.logs_for("checkout")
    second = store.logs_for("checkout")
    assert first == second
    assert first is not second  # distinct list objects


def test_mutating_returned_list_does_not_touch_store(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0)])
    returned = store.logs_for("checkout")
    returned.append(_log("checkout", 999))
    returned.clear()
    # The store is unaffected by mutations of a returned list.
    assert len(store.logs_for("checkout")) == 1


def test_runbook_corpus_returns_fresh_list(store: TelemetryStore) -> None:
    store.add_runbook_chunks([RunbookChunk(id="rb-1", title="t", source="s", text="x")])
    corpus = store.runbook_corpus()
    corpus.clear()
    assert len(store.runbook_corpus()) == 1


def test_returned_models_are_frozen(store: TelemetryStore) -> None:
    store.add_logs([_log("checkout", 0)])
    entry = store.logs_for("checkout")[0]
    with pytest.raises(ValidationError):
        entry.service = "other"  # type: ignore[misc]


def test_writer_input_is_decoupled_from_store(store: TelemetryStore) -> None:
    source = [_log("checkout", 0)]
    store.add_logs(source)
    source.append(_log("checkout", 1))  # mutate the caller's list after writing
    assert len(store.logs_for("checkout")) == 1  # store kept its own copy
