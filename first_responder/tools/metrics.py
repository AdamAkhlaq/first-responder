"""``query_metrics`` — summarise a service's metric over an anomaly window.

One of the five tools (see :mod:`first_responder.tools.base`). Unlike the other
reads, this tool does not hand back what it finds verbatim — it *summarises*. The
store may hold a single metric as several
:class:`~first_responder.schema.telemetry.MetricSeries` segments (a calm baseline
window, then a spiked anomaly window); ``query_metrics`` collapses the segments
overlapping the requested window into one summary — a ``baseline`` to compare
against and the p50/p95/p99 tail over that window — and returns only that.

**Why summarise (ADR-002).** Granularity is a deliberate product decision, not an
implementation detail. Raw points would flood the agent's finite context with
noise it cannot reason over, so the tool hands back the *shape* a human
diagnostician actually reads: a baseline, and how far the tail rose above it
during the incident. The cost of that decision is that the tool now bakes judgment
into the summary — so the summary carries an obligation. It must preserve the
signal the human would have used: a spike has to survive summarisation as p95/p99
standing well above ``baseline``. Averaging a spike away would be a silent failure
of this tool, not merely a smaller payload.

The summarisation is **deterministic and total**: it never raises and never yields
a NaN. A flat series summarises to percentiles sitting on the baseline; a window
holding no data collapses every percentile to the baseline; an unknown
service/metric comes back as a structured finding (errors-as-values, I1) rather
than an exception.
"""

from __future__ import annotations

from first_responder.schema.telemetry import MetricSeries
from first_responder.schema.time import TimeRange
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult, window_label
from first_responder.tools.registry import register


def query_metrics(
    store: TelemetryStore,
    service: str,
    metric: str,
    window: TimeRange,
) -> ToolResult[MetricSeries | None]:
    """Summarise ``service``'s ``metric`` over ``window``: a baseline plus p50/p95/p99.

    Returns the SUMMARISED :class:`~first_responder.schema.telemetry.MetricSeries`
    shape — never raw points (ADR-002; see the module docstring). When the
    service/metric pair is unknown the result is a structured "unknown
    metric/service" finding carrying ``data=None``; otherwise it is a summary whose
    p95/p99 stand above ``baseline`` exactly when the window holds a spike.
    """
    # Fetch every segment for the metric, not just those inside `window`: an empty
    # list is the "unknown metric/service" signal (distinct from a known metric with
    # no data in the window), and the baseline is read from the calm segments that
    # may sit outside the window. _summarise does the window-overlap filtering.
    segments = store.metric_series(service, metric)
    where = f"{metric!r} on {service!r}"
    if not segments:
        return ToolResult(finding=f"unknown metric/service: no series for {where}", data=None)

    summary = _summarise(segments, window)
    ratio = summary.p99 / summary.baseline if summary.baseline else 0.0
    finding = (
        f"{where} over {window_label(window)}: "
        f"baseline {summary.baseline:g} {summary.unit}; "
        f"p50/p95/p99 = {summary.p50:g}/{summary.p95:g}/{summary.p99:g} {summary.unit} "
        f"(p99 ~{ratio:.0f}x baseline)"
    )
    return ToolResult(finding=finding, data=summary)


def _summarise(segments: list[MetricSeries], window: TimeRange) -> MetricSeries:
    """Collapse the segments overlapping ``window`` into one summary over it.

    ``baseline`` is the calm floor — the lowest baseline the metric reports. The
    percentiles are those of the *worst* (highest-tailed) segment overlapping the
    window, so a spike in any sub-window survives summarisation rather than being
    averaged away, and the reported p50/p95/p99 stay a coherent triple from one
    real segment. With no overlapping segment (an empty or out-of-range window)
    every percentile collapses to ``baseline`` — a flat summary, computed without a
    NaN or an exception.
    """
    baseline = min(segment.baseline for segment in segments)
    overlapping = [s for s in segments if s.anomaly_window.overlaps(window)]
    peak = max(overlapping, key=lambda s: s.p99, default=None)
    # One code path for the tail: the worst overlapping segment's percentile triple,
    # kept intact; or a flat collapse onto the baseline when the window holds no data.
    p50, p95, p99 = (peak.p50, peak.p95, peak.p99) if peak else (baseline, baseline, baseline)
    head = segments[0]
    return MetricSeries(
        service=head.service,
        metric=head.metric,
        unit=head.unit,
        baseline=baseline,
        anomaly_window=window,
        p50=p50,
        p95=p95,
        p99=p99,
    )


register("query_metrics", query_metrics)
