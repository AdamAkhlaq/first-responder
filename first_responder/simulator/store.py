"""An in-memory telemetry store: the seam the simulator writes and the tools read.

:class:`TelemetryStore` is a *dumb* data holder. It knows nothing about scenarios,
faults, ground truth, or the agent — it holds the telemetry models from
:mod:`first_responder.schema.telemetry` and hands back slices of them. All domain
knowledge lives above it: the simulator decides what to write, the tools decide
how to query.

The API is split by trust. The ``add_*`` writers are used by the simulator to
populate the store. The readers (``logs_for``, ``metric_series``, ``traces``,
``deploys``, ``runbook_corpus``) are what the tools call. Readers are pure: every
one returns a *fresh* list, so a caller can append to or reorder the result
without touching stored state, and the elements themselves are frozen value
objects. No read mutates the store; that is what makes a run replayable and keeps
the read/write trust split a clean boundary rather than a future refactor.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

from first_responder.schema.telemetry import (
    DeployEvent,
    LogEntry,
    MetricSeries,
    RunbookChunk,
    Trace,
)
from first_responder.schema.time import TimeRange

T = TypeVar("T")


class TelemetryStore:
    """Holds telemetry collections behind a writer API and a pure reader API."""

    def __init__(self) -> None:
        self._logs: list[LogEntry] = []
        self._metric_series: list[MetricSeries] = []
        self._traces: list[Trace] = []
        self._deploys: list[DeployEvent] = []
        self._runbooks: list[RunbookChunk] = []

    # --- writers (simulator-only) --------------------------------------------

    def add_logs(self, logs: Iterable[LogEntry]) -> None:
        """Append log entries to the store."""
        self._logs.extend(logs)

    def add_metric_series(self, series: Iterable[MetricSeries]) -> None:
        """Append summarised metric series to the store."""
        self._metric_series.extend(series)

    def add_traces(self, traces: Iterable[Trace]) -> None:
        """Append request traces to the store."""
        self._traces.extend(traces)

    def add_deploys(self, deploys: Iterable[DeployEvent]) -> None:
        """Append deploy events to the store."""
        self._deploys.extend(deploys)

    def add_runbook_chunks(self, chunks: Iterable[RunbookChunk]) -> None:
        """Append runbook chunks to the retrievable corpus."""
        self._runbooks.extend(chunks)

    # --- readers (tool-facing, pure) -----------------------------------------

    @staticmethod
    def _select(items: Iterable[T], *predicates: Callable[[T], bool]) -> list[T]:
        """Return a fresh list of ``items`` satisfying every predicate.

        This is the one place the readers' shared contract lives: the result is a
        new list — so a caller cannot reach stored state through it — holding the
        frozen value objects that pass all predicates. With no predicates it simply
        copies the collection.
        """
        return [item for item in items if all(predicate(item) for predicate in predicates)]

    def logs_for(
        self,
        service: str,
        window: TimeRange | None = None,
        filter: Callable[[LogEntry], bool] | None = None,
    ) -> list[LogEntry]:
        """Log entries for ``service``, optionally narrowed to ``window`` and ``filter``.

        ``window`` keeps only entries whose timestamp falls inside it; ``filter`` is
        an arbitrary predicate the caller supplies (the store stays ignorant of what
        is being filtered on — level, message, fields, all live above it).
        """
        return self._select(
            self._logs,
            lambda e: e.service == service,
            lambda e: window is None or window.contains(e.timestamp),
            lambda e: filter is None or filter(e),
        )

    def metric_series(
        self,
        service: str,
        metric: str,
        window: TimeRange | None = None,
    ) -> list[MetricSeries]:
        """Summarised series for ``service``/``metric`` whose window overlaps ``window``."""
        return self._select(
            self._metric_series,
            lambda s: s.service == service,
            lambda s: s.metric == metric,
            lambda s: window is None or s.anomaly_window.overlaps(window),
        )

    def traces(
        self,
        request_id: str | None = None,
        service: str | None = None,
    ) -> list[Trace]:
        """Traces matching ``request_id`` and/or touching ``service`` (any span)."""
        return self._select(
            self._traces,
            lambda t: request_id is None or t.request_id == request_id,
            lambda t: service is None or any(span.service == service for span in t.spans),
        )

    def deploys(self, window: TimeRange | None = None) -> list[DeployEvent]:
        """Deploy events whose timestamp falls inside ``window`` (all of them if None)."""
        return self._select(
            self._deploys,
            lambda d: window is None or window.contains(d.timestamp),
        )

    def runbook_corpus(self) -> list[RunbookChunk]:
        """The full runbook corpus; the tool layer scores relevance, not the store."""
        return self._select(self._runbooks)
