"""Seeded, deterministic rendering helpers shared by every scenario.

This module owns the **only** source of randomness in the system. Invariant I3:
telemetry is a pure function of ``(fault, seed)`` — a scenario rendered twice with
the same seed produces byte-identical telemetry, which is what makes eval runs
comparable across prompt and tool changes. Every stochastic choice in rendering
must draw from the generator returned by :func:`seeded_rng`; nothing here (or in
any scenario) may call :func:`random.random`, :func:`time.time`,
:func:`datetime.now`, or any other unseeded or wall-clock source.

The helpers turn a fault description plus a seeded generator into the telemetry
value objects from :mod:`first_responder.schema.telemetry`. They render *shape*,
not verdicts: a metric spike, a slow downstream hop, a stream of log lines — never
a line that names the root cause.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from pydantic import JsonValue

from first_responder.schema.telemetry import (
    LogEntry,
    LogLevel,
    MetricSeries,
    Span,
    Trace,
)
from first_responder.schema.time import Seconds, TimeRange


def seeded_rng(seed: int) -> random.Random:
    """Return the system's only randomness source, seeded for reproducibility (I3).

    Use the returned :class:`random.Random` for *every* stochastic choice in
    rendering and draw from nothing else. Two generators built from the same seed
    yield the same sequence, so the telemetry rendered from them is identical; that
    determinism is what makes a run reproducible and an eval number attributable.
    """
    return random.Random(seed)


def jitter(rng: random.Random, value: float, fraction: float = 0.1) -> float:
    """Perturb ``value`` by up to ±``fraction`` of itself, drawn from ``rng``.

    Deterministic given ``rng``: it advances the generator by one draw, so callers
    that need reproducibility must pass a generator from :func:`seeded_rng`.
    """
    return value * (1.0 + rng.uniform(-fraction, fraction))


def render_log_stream(
    rng: random.Random,
    *,
    service: str,
    window: TimeRange,
    count: int,
    level: LogLevel = "info",
    message: str = "request handled",
    request_ids: Sequence[str] | None = None,
    fields: dict[str, JsonValue] | None = None,
) -> list[LogEntry]:
    """Render ``count`` log lines for ``service`` at seeded times within ``window``.

    Timestamps are drawn from ``rng`` inside the half-open ``window`` and the result
    is returned in chronological order. When ``request_ids`` is given each line is
    tagged with one (chosen via ``rng``), so a symptom in the logs can be pivoted to
    the trace that produced it.
    """
    entries = [
        LogEntry(
            timestamp=_time_in(rng, window),
            service=service,
            level=level,
            message=message,
            fields=dict(fields) if fields else {},
            request_id=rng.choice(request_ids) if request_ids else None,
        )
        for _ in range(count)
    ]
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def render_metric_series(
    rng: random.Random,
    *,
    service: str,
    metric: str,
    unit: str,
    baseline: float,
    anomaly_window: TimeRange,
    spike: float = 1.0,
    tail_ratio: float = 1.25,
    jitter_fraction: float = 0.05,
) -> MetricSeries:
    """Render a summarised series: a baseline plus tail percentiles scaled by ``spike``.

    ``spike`` is the multiplier applied to the tail during ``anomaly_window``:
    ``spike == 1.0`` is a healthy series (tails sit near baseline), ``spike > 1``
    lifts p95/p99 above baseline to encode an anomaly the agent can read as a spike.
    ``tail_ratio`` sets how much higher p99 runs than p95. Percentiles are jittered
    and then sorted, so the result always satisfies the non-decreasing-percentile
    contract of :class:`~first_responder.schema.telemetry.MetricSeries`.
    """
    p50, p95, p99 = sorted(
        (
            jitter(rng, baseline, jitter_fraction),
            jitter(rng, baseline * spike, jitter_fraction),
            jitter(rng, baseline * spike * tail_ratio, jitter_fraction),
        )
    )
    return MetricSeries(
        service=service,
        metric=metric,
        unit=unit,
        baseline=baseline,
        anomaly_window=anomaly_window,
        p50=p50,
        p95=p95,
        p99=p99,
    )


def render_flat_then_spike(
    rng: random.Random,
    *,
    service: str,
    metric: str,
    unit: str,
    baseline: float,
    baseline_window: TimeRange,
    anomaly_window: TimeRange,
    spike: float,
    tail_ratio: float = 1.25,
    jitter_fraction: float = 0.05,
) -> list[MetricSeries]:
    """Render a metric flat at baseline over one window, then spiked over the next.

    Returns two summarised series — a healthy ``baseline_window`` (``spike`` 1.0) and
    the ``anomaly_window`` scaled by ``spike``. This is the canonical sharp-onset
    shape shared by scenarios whose symptom is a metric jump: the agent reads the
    jump by comparing the two windows, and the anomaly window's start is the onset
    timestamp it correlates against a deploy or a load change. The windows are
    usually adjacent (the anomaly begins where the baseline ends) so they tile.
    """
    return [
        render_metric_series(
            rng,
            service=service,
            metric=metric,
            unit=unit,
            baseline=baseline,
            anomaly_window=baseline_window,
            spike=1.0,
            tail_ratio=tail_ratio,
            jitter_fraction=jitter_fraction,
        ),
        render_metric_series(
            rng,
            service=service,
            metric=metric,
            unit=unit,
            baseline=baseline,
            anomaly_window=anomaly_window,
            spike=spike,
            tail_ratio=tail_ratio,
            jitter_fraction=jitter_fraction,
        ),
    ]


def render_trace_chain(
    rng: random.Random,
    *,
    request_id: str,
    services: Sequence[str],
    start: Seconds,
    durations: Sequence[Seconds],
    error_from: int | None = None,
) -> Trace:
    """Render one trace as a linear parent→child span chain — the downstream hops.

    ``services[0]`` is the root; ``services[i]`` is a child span of
    ``services[i - 1]`` (the hop the agent follows downstream). ``durations[i]`` is
    span ``i``'s duration, so a slow downstream service is expressed simply by
    giving its hop the largest duration. ``error_from`` is the first index whose
    span — and every span below it — carries status ``"error"``, modelling a fault
    that originates downstream and propagates back up the chain.
    """
    spans: list[Span] = []
    span_start = start
    for index, (service, duration) in enumerate(zip(services, durations, strict=True)):
        spans.append(
            Span(
                span_id=f"{request_id}-s{index}",
                parent_span_id=f"{request_id}-s{index - 1}" if index > 0 else None,
                service=service,
                operation=f"{service}.handle",
                start=span_start,
                end=span_start + duration,
                status="error" if error_from is not None and index >= error_from else "ok",
            )
        )
        # Each child begins a small, seeded beat into its parent's window.
        span_start += 1 + rng.randrange(3)
    return Trace(request_id=request_id, spans=spans)


def _time_in(rng: random.Random, window: TimeRange) -> Seconds:
    """A seeded timestamp inside the half-open ``window`` (its start if empty)."""
    if window.duration <= 0:
        return window.start
    return rng.randrange(window.start, window.end)
