"""Determinism tests for the seeded renderer: same seed in, same telemetry out.

These pin invariant I3 — telemetry is a pure function of ``(fault, seed)``. Every
test that asserts equality across two independently-seeded generators would fail
the instant any wall-clock or unseeded randomness leaked into rendering.
"""

from __future__ import annotations

from first_responder.schema.time import TimeRange
from first_responder.simulator.render import (
    jitter,
    render_flat_then_spike,
    render_log_stream,
    render_metric_series,
    render_trace_chain,
    seeded_rng,
)

# --- the generator itself -----------------------------------------------------


def test_seeded_rng_same_seed_yields_same_sequence() -> None:
    a = seeded_rng(7)
    b = seeded_rng(7)
    assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]


def test_seeded_rng_different_seed_diverges() -> None:
    a = seeded_rng(1)
    b = seeded_rng(2)
    assert [a.random() for _ in range(20)] != [b.random() for _ in range(20)]


# --- jitter -------------------------------------------------------------------


def test_jitter_is_deterministic_and_bounded() -> None:
    assert jitter(seeded_rng(9), 100.0, fraction=0.1) == jitter(seeded_rng(9), 100.0, fraction=0.1)
    value = jitter(seeded_rng(9), 100.0, fraction=0.1)
    assert 90.0 <= value <= 110.0


# --- log stream ---------------------------------------------------------------


def test_render_log_stream_is_deterministic() -> None:
    kwargs = {
        "service": "checkout",
        "window": TimeRange(start=0, end=300),
        "count": 8,
        "request_ids": ["r1", "r2", "r3"],
    }
    assert render_log_stream(seeded_rng(42), **kwargs) == render_log_stream(
        seeded_rng(42), **kwargs
    )


def test_render_log_stream_is_well_formed() -> None:
    window = TimeRange(start=0, end=300)
    stream = render_log_stream(seeded_rng(42), service="checkout", window=window, count=8)
    assert len(stream) == 8
    assert all(window.contains(entry.timestamp) for entry in stream)  # inside the window
    assert [e.timestamp for e in stream] == sorted(e.timestamp for e in stream)  # chronological


def test_render_log_stream_different_seed_differs_but_keeps_shape() -> None:
    window = TimeRange(start=0, end=300)
    a = render_log_stream(seeded_rng(1), service="checkout", window=window, count=8)
    b = render_log_stream(seeded_rng(2), service="checkout", window=window, count=8)
    assert a != b
    assert len(a) == len(b) == 8  # different timestamps, same structure


# --- metric series ------------------------------------------------------------


def _series_kwargs(spike: float) -> dict[str, object]:
    return {
        "service": "payments",
        "metric": "latency_ms",
        "unit": "ms",
        "baseline": 40.0,
        "anomaly_window": TimeRange(start=0, end=120),
        "spike": spike,
    }


def test_render_metric_series_is_deterministic_and_valid() -> None:
    first = render_metric_series(seeded_rng(3), **_series_kwargs(spike=10.0))
    second = render_metric_series(seeded_rng(3), **_series_kwargs(spike=10.0))
    assert first == second
    assert first.p50 <= first.p95 <= first.p99  # the percentile contract holds
    assert first.p99 > first.baseline  # the spike shows up in the tail


def test_render_metric_series_spike_lifts_the_tail() -> None:
    healthy = render_metric_series(seeded_rng(3), **_series_kwargs(spike=1.0))
    spiked = render_metric_series(seeded_rng(3), **_series_kwargs(spike=10.0))
    assert spiked.p99 > healthy.p99


def _flat_then_spike_kwargs() -> dict[str, object]:
    return {
        "service": "checkout",
        "metric": "error_rate",
        "unit": "errors/s",
        "baseline": 0.4,
        "baseline_window": TimeRange(start=-300, end=0),
        "anomaly_window": TimeRange(start=0, end=300),
        "spike": 20.0,
    }


def test_render_flat_then_spike_is_deterministic_and_shaped() -> None:
    first = render_flat_then_spike(seeded_rng(11), **_flat_then_spike_kwargs())
    second = render_flat_then_spike(seeded_rng(11), **_flat_then_spike_kwargs())
    assert first == second
    flat, spiked = first
    assert flat.anomaly_window.end == spiked.anomaly_window.start  # adjacent windows tile
    assert spiked.p99 > flat.p99 * 5  # the spike lifts the tail well above baseline


# --- trace chain --------------------------------------------------------------


def _trace_kwargs() -> dict[str, object]:
    return {
        "request_id": "req-1",
        "services": ["checkout", "payments", "ledger"],
        "start": 0,
        "durations": [900, 850, 800],
        "error_from": 2,
    }


def test_render_trace_chain_is_deterministic() -> None:
    assert render_trace_chain(seeded_rng(5), **_trace_kwargs()) == render_trace_chain(
        seeded_rng(5), **_trace_kwargs()
    )


def test_render_trace_chain_has_downstream_hop() -> None:
    trace = render_trace_chain(seeded_rng(5), **_trace_kwargs())
    assert trace.spans[0].parent_span_id is None  # root
    # Each span is a child of the one before it — the hop the agent follows.
    assert trace.spans[1].parent_span_id == trace.spans[0].span_id
    assert trace.spans[2].parent_span_id == trace.spans[1].span_id


def test_render_trace_chain_error_originates_downstream() -> None:
    trace = render_trace_chain(seeded_rng(5), **_trace_kwargs())  # error_from=2
    assert [span.status for span in trace.spans] == ["ok", "ok", "error"]
