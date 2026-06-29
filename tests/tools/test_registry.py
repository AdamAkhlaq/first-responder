"""Tests for the tool registry and dispatch: routing, arg validation, errors-as-values."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import first_responder.tools.registry as registry_module
from first_responder.schema.telemetry import LogEntry
from first_responder.schema.time import TimeRange
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolError, ToolResult
from first_responder.tools.registry import ToolCall, dispatch, register

# --- stub tools ---------------------------------------------------------------
#
# Stand-ins for the real tools (which arrive in later steps). Each is a pure read
# over the store that returns a structured ToolResult — including a populated
# "nothing matched" finding rather than raising — so the registry/dispatch contract
# can be exercised on its own.


def _stub_logs(store: TelemetryStore, service: str) -> ToolResult[list[LogEntry]]:
    """Surface a service's logs, or a structured 'no logs' finding when there are none."""
    logs = store.logs_for(service)
    if not logs:
        return ToolResult(finding=f"no logs for service {service!r} in the store", data=[])
    return ToolResult(finding=f"{len(logs)} log(s) for service {service!r}", data=logs)


def _stub_logs_in_window(
    store: TelemetryStore, service: str, window: TimeRange
) -> ToolResult[list[LogEntry]]:
    """Like :func:`_stub_logs` but narrowed to ``window`` — exercises JSON→model coercion."""
    logs = store.logs_for(service, window=window)
    return ToolResult(finding=f"{len(logs)} log(s) in window", data=logs)


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    # Run each test against an empty registry, then restore the original — so a
    # self-registering tool imported elsewhere can't perturb these tests and these
    # tests don't leak their stubs into the real registry.
    saved = dict(registry_module._REGISTRY)
    registry_module._REGISTRY.clear()
    try:
        yield
    finally:
        registry_module._REGISTRY.clear()
        registry_module._REGISTRY.update(saved)


@pytest.fixture
def store() -> TelemetryStore:
    s = TelemetryStore()
    s.add_logs([LogEntry(timestamp=5, service="checkout", level="error", message="boom")])
    return s


# --- registration -------------------------------------------------------------


def test_register_returns_the_unwrapped_function() -> None:
    assert register("logs", _stub_logs) is _stub_logs


def test_register_rejects_duplicate_name() -> None:
    register("logs", _stub_logs)
    with pytest.raises(ValueError, match="already registered"):
        register("logs", _stub_logs)


# --- successful dispatch ------------------------------------------------------


def test_dispatch_routes_to_registered_tool(store: TelemetryStore) -> None:
    register("logs", _stub_logs)
    result = dispatch(ToolCall(tool="logs", args={"service": "checkout"}), store)
    assert isinstance(result, ToolResult)
    assert [e.service for e in result.data] == ["checkout"]
    assert "1 log" in result.finding


def test_dispatch_coerces_json_args_into_models(store: TelemetryStore) -> None:
    # The window arrives as a JSON object and must be coerced to a TimeRange before
    # the tool sees it — that coercion is the "args type-check" half of the contract.
    register("logs_in_window", _stub_logs_in_window)
    call = ToolCall(
        tool="logs_in_window",
        args={"service": "checkout", "window": {"start": 0, "end": 60}},
    )
    result = dispatch(call, store)
    assert [e.timestamp for e in result.data] == [5]


def test_dispatch_binds_the_store_given_at_call_time() -> None:
    register("logs", _stub_logs)
    populated = TelemetryStore()
    populated.add_logs([LogEntry(timestamp=0, service="checkout", level="info", message="m")])
    empty = TelemetryStore()
    call = ToolCall(tool="logs", args={"service": "checkout"})
    assert dispatch(call, populated).data != []
    assert dispatch(call, empty).data == []


# --- errors-as-values: an empty match is a finding, not an exception ----------


def test_empty_result_is_returned_as_a_finding_not_raised(store: TelemetryStore) -> None:
    register("logs", _stub_logs)
    # A well-formed query that matches nothing must come back as a structured result.
    result = dispatch(ToolCall(tool="logs", args={"service": "no-such-service"}), store)
    assert isinstance(result, ToolResult)
    assert result.data == []
    assert "no logs" in result.finding


# --- ToolError: caller misuse -------------------------------------------------


def test_unknown_tool_raises_tool_error(store: TelemetryStore) -> None:
    register("logs", _stub_logs)
    with pytest.raises(ToolError, match="unknown tool 'nope'") as exc:
        dispatch(ToolCall(tool="nope", args={}), store)
    assert "logs" in str(exc.value)  # the message lists what *is* registered


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({}, "missing required argument"),
        ({"service": 123}, "wrong-typed argument"),
        ({"service": "checkout", "bogus": 1}, "unexpected argument"),
    ],
)
def test_bad_args_raise_tool_error(
    store: TelemetryStore, args: dict[str, object], reason: str
) -> None:
    register("logs", _stub_logs)
    with pytest.raises(ToolError, match="invalid arguments for tool 'logs'"):
        dispatch(ToolCall(tool="logs", args=args), store)  # type: ignore[arg-type]
