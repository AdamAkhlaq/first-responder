"""Tests for the bad_deploy scenario: determinism, timestamp alignment, leak gate."""

from __future__ import annotations

import pytest

from first_responder.schema.telemetry import LogEntry
from first_responder.schema.time import TimeRange
from first_responder.simulator.scenario import get_scenario
from first_responder.simulator.scenarios.bad_deploy import (
    AFFECTED_SERVICE,
    BAD_DEPLOY,
    T0,
    UNRELATED_SERVICE,
)
from tests.simulator.leak_guard import assert_no_verbatim_leak

SEED = 7
_WIDE = TimeRange(start=T0 - 600, end=T0 + 600)


# --- registration & contract --------------------------------------------------


def test_registered_under_its_name() -> None:
    assert BAD_DEPLOY.name == "bad_deploy"
    assert get_scenario("bad_deploy") is BAD_DEPLOY


def test_ground_truth_contract() -> None:
    truth = BAD_DEPLOY.ground_truth()
    assert truth.remediation_class == "rollback"
    assert truth.min_evidence_path == ["query_metrics", "query_deploys"]
    assert truth.root_cause  # names the cause for the scorer; never shown to the agent


# --- determinism (invariant I3) -----------------------------------------------


def test_activate_is_deterministic_for_a_seed() -> None:
    first_store, first_alert = BAD_DEPLOY.activate(SEED)
    second_store, second_alert = BAD_DEPLOY.activate(SEED)
    assert first_store.metric_series(
        AFFECTED_SERVICE, "error_rate", _WIDE
    ) == second_store.metric_series(AFFECTED_SERVICE, "error_rate", _WIDE)
    assert first_store.logs_for(AFFECTED_SERVICE) == second_store.logs_for(AFFECTED_SERVICE)
    assert first_store.deploys() == second_store.deploys()
    assert first_alert == second_alert


def test_activate_differs_across_seeds() -> None:
    one, _ = BAD_DEPLOY.activate(1)
    two, _ = BAD_DEPLOY.activate(2)
    assert one.logs_for(AFFECTED_SERVICE) != two.logs_for(AFFECTED_SERVICE)


def test_activate_returns_a_fresh_store_each_call() -> None:
    a, _ = BAD_DEPLOY.activate(SEED)
    b, _ = BAD_DEPLOY.activate(SEED)
    assert a is not b


# --- the core signal: spike onset aligns with the deploy ----------------------


def test_single_deploy_at_t0_for_affected_service() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    deploys = store.deploys()
    assert len(deploys) == 1
    assert deploys[0].service == AFFECTED_SERVICE
    assert deploys[0].timestamp == T0


def test_error_rate_is_flat_then_spikes_at_t0() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    series = store.metric_series(AFFECTED_SERVICE, "error_rate", _WIDE)
    by_onset = {s.anomaly_window.start: s for s in series}
    # A flat pre-incident window and the spiked incident window starting at T0.
    assert set(by_onset) == {T0 - 300, T0}
    flat, spike = by_onset[T0 - 300], by_onset[T0]
    assert spike.anomaly_window.start == T0  # onset coincides with the deploy
    assert spike.p99 > flat.p99 * 5  # a sharp jump, not baseline noise


def test_symptom_onset_and_deploy_share_a_timestamp() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    deploy = store.deploys()[0]
    spike = next(
        s
        for s in store.metric_series(AFFECTED_SERVICE, "error_rate", _WIDE)
        if s.p99 > s.baseline * 5
    )
    assert spike.anomaly_window.start == deploy.timestamp


def test_corroborating_error_logs_follow_the_onset() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    errors = store.logs_for(AFFECTED_SERVICE, filter=lambda e: e.level == "error")
    assert errors
    assert all(entry.timestamp >= T0 for entry in errors)


# --- the planted red herring --------------------------------------------------


def test_red_herring_is_present_but_uncorrelated() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    herring = store.metric_series(UNRELATED_SERVICE, "latency_ms", _WIDE)
    assert herring  # a wobble exists on the unrelated service
    # ...but nothing deployed on it, so it doesn't correlate with the symptom,
    assert all(d.service == AFFECTED_SERVICE for d in store.deploys())
    # ...and it is a mild blip, not a sharp spike.
    assert herring[0].p99 < herring[0].baseline * 3


# --- the alert states the symptom, not the cause ------------------------------


def test_alert_describes_symptom_not_cause() -> None:
    _, alert = BAD_DEPLOY.activate(SEED)
    assert alert.service == AFFECTED_SERVICE
    assert alert.fired_at >= T0
    assert "deploy" not in alert.symptom.lower()


# --- the eval-validity gate ---------------------------------------------------


def test_no_verbatim_leak() -> None:
    store, alert = BAD_DEPLOY.activate(SEED)
    assert_no_verbatim_leak(store, alert, BAD_DEPLOY.ground_truth())


def test_leak_guard_catches_a_planted_leak() -> None:
    # Prove the guard works: plant the root cause verbatim into a log line.
    store, alert = BAD_DEPLOY.activate(SEED)
    truth = BAD_DEPLOY.ground_truth()
    store.add_logs(
        [LogEntry(timestamp=T0, service=AFFECTED_SERVICE, level="error", message=truth.root_cause)]
    )
    with pytest.raises(AssertionError, match="leaked verbatim"):
        assert_no_verbatim_leak(store, alert, truth)
