"""The tool contract: pure, read-only views of a TelemetryStore that return findings.

The five tools (``query_logs``, ``query_metrics``, ``get_traces``,
``query_deploys``, ``search_runbooks``) are the *only* interface between the agent
and the world (invariant I1). The agent never reaches into the
:class:`~first_responder.simulator.store.TelemetryStore` or the simulator directly —
it perceives telemetry exclusively through these tools. That single boundary is what
keeps the agent a pure reasoner over an interface, not a consumer of implementation
detail, and it is what every later layer composes against.

Every tool obeys the same contract:

* **Pure and read-only.** A tool is a function ``(store, **args) -> ToolResult``. It
  reads the store and computes; it never writes, mutates, or reaches outside the
  store. Given the same populated store and the same args it returns the same result.
* **Errors are values.** *Absence is information, not failure.* "No traces in the
  window", "unknown metric", "no matching logs" are ordinary, expected answers a
  diagnostician reasons from — so a tool returns them as a populated
  :class:`ToolResult` whose ``finding`` describes the absence, never as a raised
  exception. An empty result is a finding, not an error.
* **Exceptions mean misuse.** The one thing a tool *does* raise is :class:`ToolError`,
  and only for genuine caller error — a tool that does not exist, or arguments that do
  not type-check. That is a bug in the caller, categorically different from a
  well-formed query that happened to match nothing.

This split is invariant **I1** for the tool layer, and the property the whole stack
leans on: a returned :class:`ToolResult` is *always* a real answer, and an exception
*always* means the caller asked the wrong question — never that the world was empty.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from first_responder.schema.time import TimeRange

DataT = TypeVar("DataT")


class ToolError(Exception):
    """A tool was *called wrong* — it does not exist, or its arguments are invalid.

    Reserved for caller misuse and deliberately distinct from an empty result: "no
    logs matched" is a :class:`ToolResult`, while "there is no such tool" or
    "``window`` is not a TimeRange" is a :class:`ToolError`. Absence is a value; only
    malformed calls raise.
    """


class ToolResult(BaseModel, Generic[DataT]):
    """A tool's answer: a human-readable ``finding`` and its typed ``data`` payload.

    ``finding`` is always populated — it is the one-line summary the agent reads and
    the evidence ledger records, and it carries the informative message in the
    *absence* case ("no traces in the window") exactly as much as in the present case.
    ``data`` is the typed payload: a list of telemetry models, a single summary, or an
    empty collection when nothing matched. A result whose ``data`` is empty is a valid
    finding, not an error — see the module docstring.
    """

    model_config = ConfigDict(frozen=True)

    finding: str
    data: DataT


# A tool is a pure function over a store: ``(store, **args) -> ToolResult``. The
# registry holds these and ``dispatch`` binds the store to one at call time.
Tool = Callable[..., ToolResult[Any]]


def window_label(window: TimeRange) -> str:
    """Render ``window`` as the half-open interval ``[start, end)`` for a finding.

    Centralised so every tool describes a time window the same way — the agent and
    the eval harness read one uniform grammar across all five tools' findings.
    """
    return f"[{window.start}, {window.end})"
