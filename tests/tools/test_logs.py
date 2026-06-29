"""Tests for query_logs over the bad_deploy scenario: window scoping, filter, empty findings."""

from __future__ import annotations

import pytest

from first_responder.schema.telemetry import LogEntry
from first_responder.schema.time import TimeRange
from first_responder.simulator.scenarios.bad_deploy import AFFECTED_SERVICE, BAD_DEPLOY, T0
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult
from first_responder.tools.logs import query_logs
from first_responder.tools.registry import ToolCall, dispatch

SEED = 7
_INCIDENT = TimeRange.since(T0, 300)  # [0, 300): the error logs
_PRE = TimeRange(start=T0 - 300, end=T0)  # [-300, 0): the healthy info logs
_BEFORE_ALL = TimeRange(start=T0 - 600, end=T0 - 300)  # well before any log


@pytest.fixture
def store() -> TelemetryStore:
    activated, _ = BAD_DEPLOY.activate(SEED)
    return activated


# --- the core read ------------------------------------------------------------


def test_returns_error_logs_around_t0(store: TelemetryStore) -> None:
    result = query_logs(store, AFFECTED_SERVICE, _INCIDENT)
    assert isinstance(result, ToolResult)
    assert result.data
    assert all(entry.level == "error" and entry.timestamp >= T0 for entry in result.data)
    assert "HTTP 500" in result.data[0].message  # the symptom, never the cause


def test_window_scopes_to_pre_incident_info_logs(store: TelemetryStore) -> None:
    result = query_logs(store, AFFECTED_SERVICE, _PRE)
    assert result.data
    assert all(entry.level == "info" for entry in result.data)  # error logs are post-T0


# --- the optional filter ------------------------------------------------------


def test_filter_is_case_insensitive_over_message(store: TelemetryStore) -> None:
    result = query_logs(store, AFFECTED_SERVICE, _INCIDENT, filter="http 500")
    assert result.data
    assert all("500" in entry.message for entry in result.data)
    assert "matching 'http 500'" in result.finding


def test_filter_excluding_everything_returns_empty_finding(store: TelemetryStore) -> None:
    result = query_logs(store, AFFECTED_SERVICE, _INCIDENT, filter="no-such-text-anywhere")
    assert result.data == []
    assert "no logs" in result.finding


def test_filter_matches_structured_fields() -> None:
    store = TelemetryStore()
    store.add_logs(
        [
            LogEntry(
                timestamp=1,
                service="checkout",
                level="warn",
                message="connection wait",
                fields={"pool": "payments-db"},
            ),
            LogEntry(timestamp=2, service="checkout", level="info", message="handled", fields={}),
        ]
    )
    result = query_logs(store, "checkout", TimeRange(start=0, end=10), filter="payments-db")
    assert [entry.message for entry in result.data] == ["connection wait"]


# --- empty window before the incident -----------------------------------------


def test_empty_finding_for_window_before_incident(store: TelemetryStore) -> None:
    result = query_logs(store, AFFECTED_SERVICE, _BEFORE_ALL)
    assert result.data == []
    assert "no logs" in result.finding
    assert f"[{_BEFORE_ALL.start}, {_BEFORE_ALL.end})" in result.finding


# --- registered & dispatchable ------------------------------------------------


def test_query_logs_is_registered_and_dispatchable(store: TelemetryStore) -> None:
    call = ToolCall(
        tool="query_logs",
        args={"service": AFFECTED_SERVICE, "window": {"start": T0, "end": 300}},
    )
    result = dispatch(call, store)
    assert result.data
    assert all(entry.service == AFFECTED_SERVICE for entry in result.data)
