"""Tests for the bad_deploy scenario: determinism, timestamp alignment, leak gate."""

from __future__ import annotations

from first_responder.schema.time import TimeRange
from first_responder.simulator.scenario import get_scenario
from first_responder.simulator.scenarios.bad_deploy import (
    AFFECTED_SERVICE,
    BAD_DEPLOY,
    T0,
    UNRELATED_SERVICE,
)
from tests.simulator.leak_guard import (
    assert_leak_guard_detects_planted_leak,
    assert_no_verbatim_leak,
)
from tests.simulator.scenario_asserts import (
    assert_activation_varies_by_seed,
    assert_alert_states_symptom_not_cause,
    assert_deterministic_activation,
    error_logs,
    series_by_onset,
)

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
    assert_deterministic_activation(BAD_DEPLOY, SEED)


def test_activate_differs_across_seeds() -> None:
    assert_activation_varies_by_seed(BAD_DEPLOY)


# --- the core signal: spike onset aligns with the deploy ----------------------


def test_single_deploy_at_t0_for_affected_service() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    deploys = store.deploys()
    assert len(deploys) == 1
    assert deploys[0].service == AFFECTED_SERVICE
    assert deploys[0].timestamp == T0


def test_error_rate_is_flat_then_spikes_at_t0() -> None:
    store, _ = BAD_DEPLOY.activate(SEED)
    by_onset = series_by_onset(store, AFFECTED_SERVICE, "error_rate", _WIDE)
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
    errors = error_logs(store, AFFECTED_SERVICE)
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
    assert_alert_states_symptom_not_cause(
        alert, service=AFFECTED_SERVICE, t0=T0, forbidden=["deploy"]
    )


# --- the eval-validity gate ---------------------------------------------------


def test_no_verbatim_leak() -> None:
    store, alert = BAD_DEPLOY.activate(SEED)
    assert_no_verbatim_leak(store, alert, BAD_DEPLOY.ground_truth())


def test_leak_guard_catches_a_planted_leak() -> None:
    store, alert = BAD_DEPLOY.activate(SEED)
    assert_leak_guard_detects_planted_leak(
        store, alert, BAD_DEPLOY.ground_truth(), service=AFFECTED_SERVICE, t0=T0
    )
