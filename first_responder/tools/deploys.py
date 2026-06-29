"""``query_deploys`` — read deploy events within a time window.

One of the five tools (see :mod:`first_responder.tools.base`). A pure read over
:meth:`~first_responder.simulator.store.TelemetryStore.deploys`; beyond delegating, its
only job is to wrap the result in a structured finding so an empty window is
information ("no deploys in window"), not an exception.
"""

from __future__ import annotations

from first_responder.schema.telemetry import DeployEvent
from first_responder.schema.time import TimeRange
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult, window_label
from first_responder.tools.registry import register


def query_deploys(store: TelemetryStore, window: TimeRange) -> ToolResult[list[DeployEvent]]:
    """Deploy events whose timestamp falls within ``window``.

    Correlating a deploy against a symptom onset is the event-correlation signal the
    agent relies on (the ``bad_deploy`` scenario). An empty window comes back as a
    finding, not raised — the *absence* of a deploy is itself a useful answer.
    """
    deploys = store.deploys(window=window)
    where = window_label(window)
    if not deploys:
        return ToolResult(finding=f"no deploys in window {where}", data=[])
    return ToolResult(finding=f"{len(deploys)} deploy(s) in window {where}", data=deploys)


register("query_deploys", query_deploys)
