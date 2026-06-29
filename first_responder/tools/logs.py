"""``query_logs`` — read a service's log entries within a time window.

One of the five tools (see :mod:`first_responder.tools.base`). It is a thin, pure
read over :meth:`~first_responder.simulator.store.TelemetryStore.logs_for`: the store
owns service- and window-filtering, and this tool adds only the agent-facing layer —
an optional free-text ``filter`` and a structured finding, so an empty window reads
as information ("no matching logs") rather than raising (errors-as-values, I1).
"""

from __future__ import annotations

from collections.abc import Callable

from first_responder.schema.telemetry import LogEntry
from first_responder.schema.time import TimeRange
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult, window_label
from first_responder.tools.registry import register


def query_logs(
    store: TelemetryStore,
    service: str,
    window: TimeRange,
    filter: str | None = None,
) -> ToolResult[list[LogEntry]]:
    """Logs for ``service`` within ``window``, optionally narrowed by ``filter``.

    ``filter`` is a case-insensitive substring matched over each entry's ``message``
    and its structured ``fields`` — the agent's way of homing in on, say, ``"500"`` or
    a request id without the store needing to know what is being matched on. An empty
    match is returned as a populated ``finding``, not raised: absence of logs in a
    window is itself diagnostic.
    """
    predicate = _contains(filter) if filter is not None else None
    matched = store.logs_for(service, window=window, filter=predicate)
    where = f"{service!r} in {window_label(window)}"
    qualifier = f" matching {filter!r}" if filter is not None else ""
    if not matched:
        return ToolResult(finding=f"no logs for {where}{qualifier}", data=[])
    return ToolResult(finding=f"{len(matched)} log(s) for {where}{qualifier}", data=matched)


def _contains(term: str) -> Callable[[LogEntry], bool]:
    """A case-insensitive predicate matching ``term`` over a log's message and fields."""
    needle = term.lower()

    def predicate(entry: LogEntry) -> bool:
        if needle in entry.message.lower():
            return True
        return any(needle in f"{key} {value}".lower() for key, value in entry.fields.items())

    return predicate


register("query_logs", query_logs)
