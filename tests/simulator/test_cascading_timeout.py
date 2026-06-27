"""Tests for cascading_timeout: the A→B trace hop, B's spike, the healthy-A herring."""

from __future__ import annotations

from first_responder.schema.time import TimeRange
from first_responder.simulator.scenario import get_scenario
from first_responder.simulator.scenarios.cascading_timeout import (
    AFFECTED_SERVICE,
    CASCADING_TIMEOUT,
    DOWNSTREAM_SERVICE,
    T0,
)
from tests.simulator.leak_guard import assert_no_verbatim_leak

SEED = 13
_WIDE = TimeRange(start=T0 - 600, end=T0 + 600)


# --- registration & contract --------------------------------------------------


def test_registered_under_its_name() -> None:
    assert CASCADING_TIMEOUT.name == "cascading_timeout"
    assert get_scenario("cascading_timeout") is CASCADING_TIMEOUT


def test_ground_truth_contract() -> None:
    truth = CASCADING_TIMEOUT.ground_truth()
    assert truth.remediation_class == "scale"
    assert truth.min_evidence_path == ["query_logs", "get_traces", "query_metrics"]
    assert truth.root_cause


# --- determinism (invariant I3) -----------------------------------------------


def test_activate_is_deterministic_for_a_seed() -> None:
    first_store, first_alert = CASCADING_TIMEOUT.activate(SEED)
    second_store, second_alert = CASCADING_TIMEOUT.activate(SEED)
    assert first_store.traces() == second_store.traces()
    assert first_store.logs_for(AFFECTED_SERVICE) == second_store.logs_for(AFFECTED_SERVICE)
    assert first_store.metric_series(
        DOWNSTREAM_SERVICE, "latency_ms", _WIDE
    ) == second_store.metric_series(DOWNSTREAM_SERVICE, "latency_ms", _WIDE)
    assert first_alert == second_alert


def test_activate_differs_across_seeds() -> None:
    one, _ = CASCADING_TIMEOUT.activate(1)
    two, _ = CASCADING_TIMEOUT.activate(2)
    assert one.traces() != two.traces()


# --- the trace hop: A -> B, with B as the slow span ---------------------------


def test_trace_hop_a_to_b_with_b_dominating_latency() -> None:
    store, _ = CASCADING_TIMEOUT.activate(SEED)
    traces = store.traces(service=DOWNSTREAM_SERVICE)
    assert traces  # every request touches B
    trace = traces[0]
    a_span = next(s for s in trace.spans if s.service == AFFECTED_SERVICE)
    b_span = next(s for s in trace.spans if s.service == DOWNSTREAM_SERVICE)
    # The hop: B is a child span of A — one downstream step.
    assert b_span.parent_span_id == a_span.span_id
    # B is the slow span: it accounts for the majority of A's request time.
    assert b_span.duration > a_span.duration / 2


# --- the cause: B's latency spikes at T0 --------------------------------------


def test_downstream_b_latency_spikes_at_t0() -> None:
    store, _ = CASCADING_TIMEOUT.activate(SEED)
    series = store.metric_series(DOWNSTREAM_SERVICE, "latency_ms", _WIDE)
    assert len(series) == 2  # a flat pre window and the spiked incident window
    spike = max(series, key=lambda s: s.p99)
    flat = min(series, key=lambda s: s.p99)
    assert spike.anomaly_window.start == T0  # onset at the incident origin
    assert spike.p99 > flat.p99 * 5  # a sharp jump, not baseline noise


# --- the symptom: A's timeout logs --------------------------------------------


def test_service_a_logs_show_timeouts_after_onset() -> None:
    store, _ = CASCADING_TIMEOUT.activate(SEED)
    timeouts = store.logs_for(AFFECTED_SERVICE, filter=lambda e: e.level == "error")
    assert timeouts
    assert all(entry.timestamp >= T0 for entry in timeouts)
    assert all("timed out" in entry.message.lower() for entry in timeouts)
    # ...and the log does not name the downstream culprit — that needs the trace.
    assert all(DOWNSTREAM_SERVICE not in entry.message for entry in timeouts)


# --- the red herring: A's own health looks normal -----------------------------


def test_service_a_health_metrics_look_normal() -> None:
    store, _ = CASCADING_TIMEOUT.activate(SEED)
    a_cpu = store.metric_series(AFFECTED_SERVICE, "cpu_utilization", _WIDE)
    assert a_cpu  # A's resource metric is present...
    assert all(s.p99 < s.baseline * 2 for s in a_cpu)  # ...and healthy, not spiked


# --- the alert states the symptom, not the cause ------------------------------


def test_alert_describes_symptom_not_cause() -> None:
    _, alert = CASCADING_TIMEOUT.activate(SEED)
    assert alert.service == AFFECTED_SERVICE
    assert alert.fired_at >= T0
    assert DOWNSTREAM_SERVICE not in alert.symptom  # never names the downstream cause


# --- the eval-validity gate ---------------------------------------------------


def test_no_verbatim_leak() -> None:
    store, alert = CASCADING_TIMEOUT.activate(SEED)
    assert_no_verbatim_leak(store, alert, CASCADING_TIMEOUT.ground_truth())
