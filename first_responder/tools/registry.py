"""The tool registry and dispatch — the agent's single, uniform call surface.

Tools register here by name. The agent emits a :class:`ToolCall` (a tool name plus
JSON args) and :func:`dispatch` validates it and routes it to the tool over a given
store. Exactly two things become a :class:`ToolError`: naming a tool that is not
registered, and passing arguments that do not type-check against the tool's
signature. Everything else — including a well-formed call that matched no data —
comes back as a :class:`ToolResult` (errors-as-values; see
:mod:`first_responder.tools.base`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, validate_call

from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import Tool, ToolError, ToolResult


class ToolCall(BaseModel):
    """A request to run ``tool`` with ``args`` — the action the agent emits.

    ``args`` are JSON-shaped keyword arguments (the agent speaks JSON, not Python):
    :func:`dispatch` validates and coerces them against the target tool's signature,
    so a window arrives as ``{"start": ..., "end": ...}`` and is coerced into a
    :class:`~first_responder.schema.time.TimeRange` before the tool runs.
    """

    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, JsonValue] = Field(default_factory=dict)


_REGISTRY: dict[str, Tool] = {}

# Every tool takes the TelemetryStore as its first argument; the store is a plain
# class, not a pydantic model, so validate_call must be told to accept it as-is.
_VALIDATE_ARGS = validate_call(config=ConfigDict(arbitrary_types_allowed=True))


def register(name: str, fn: Tool) -> Tool:
    """Register ``fn`` as the tool ``name`` and return it (unwrapped) for direct use.

    The stored callable is wrapped so the function's type annotations validate
    incoming arguments — that is what lets :func:`dispatch` reject a malformed call
    with a :class:`ToolError` before the tool body runs. A duplicate name is a
    programming error.
    """
    if name in _REGISTRY:
        raise ValueError(f"tool {name!r} is already registered")
    _REGISTRY[name] = _VALIDATE_ARGS(fn)
    return fn


def dispatch(call: ToolCall, store: TelemetryStore) -> ToolResult[Any]:
    """Validate ``call`` and route it to its tool over ``store``.

    Raises :class:`ToolError` if the tool is unknown or its arguments do not
    type-check; otherwise returns the tool's :class:`ToolResult` — including the
    structured empty-result finding when nothing matched, which is an answer, not an
    error.
    """
    try:
        tool = _REGISTRY[call.tool]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise ToolError(f"unknown tool {call.tool!r}; registered tools: {known}") from None
    try:
        return tool(store, **call.args)
    except ValidationError as exc:
        raise ToolError(f"invalid arguments for tool {call.tool!r}: {exc}") from exc
