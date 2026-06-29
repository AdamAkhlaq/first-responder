"""Tests for query_deploys over the bad_deploy scenario: the deploy at T0, empty findings."""

from __future__ import annotations

import pytest

from first_responder.schema.time import TimeRange
from first_responder.simulator.scenarios.bad_deploy import AFFECTED_SERVICE, BAD_DEPLOY, T0
from first_responder.simulator.store import TelemetryStore
from first_responder.tools.base import ToolResult
from first_responder.tools.deploys import query_deploys
from first_responder.tools.registry import ToolCall, dispatch

SEED = 7
_INCIDENT = TimeRange.since(T0, 300)  # [0, 300): contains the deploy at T0
_PRE = TimeRange(start=T0 - 300, end=T0)  # [-300, 0): before the deploy


@pytest.fixture
def store() -> TelemetryStore:
    activated, _ = BAD_DEPLOY.activate(SEED)
    return activated


def test_surfaces_the_deploy_at_t0(store: TelemetryStore) -> None:
    result = query_deploys(store, _INCIDENT)
    assert isinstance(result, ToolResult)
    assert len(result.data) == 1
    deploy = result.data[0]
    assert deploy.service == AFFECTED_SERVICE
    assert deploy.timestamp == T0
    assert "1 deploy" in result.finding


def test_empty_finding_for_window_before_incident(store: TelemetryStore) -> None:
    result = query_deploys(store, _PRE)
    assert result.data == []
    assert "no deploys" in result.finding
    assert f"[{_PRE.start}, {_PRE.end})" in result.finding


def test_query_deploys_is_registered_and_dispatchable(store: TelemetryStore) -> None:
    call = ToolCall(tool="query_deploys", args={"window": {"start": T0, "end": 300}})
    result = dispatch(call, store)
    assert len(result.data) == 1
    assert result.data[0].timestamp == T0
