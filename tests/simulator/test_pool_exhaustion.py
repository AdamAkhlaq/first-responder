"""Tests for pool_exhaustion: determinism, failure↔saturation correlation, deploy herring."""

from __future__ import annotations

from first_responder.schema.time import TimeRange
from first_responder.simulator.scenario import get_scenario
from first_responder.simulator.scenarios.pool_exhaustion import (
    AFFECTED_SERVICE,
    LOAD_METRIC,
    POOL_EXHAUSTION,
    POOL_METRIC,
    T0,
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

SEED = 21
_WIDE = TimeRange(start=T0 - 600, end=T0 + 600)

# Thresholds for reading the summarised shapes: load is a "peak" when its tail runs
# well above baseline, the pool is "saturated" when its tail pins near the ceiling.
_LOAD_PEAK_FACTOR = 2.0
_POOL_SATURATED_PCT = 90.0


# --- registration & contract --------------------------------------------------


def test_registered_under_its_name() -> None:
    assert POOL_EXHAUSTION.name == "pool_exhaustion"
    assert get_scenario("pool_exhaustion") is POOL_EXHAUSTION


def test_ground_truth_contract() -> None:
    truth = POOL_EXHAUSTION.ground_truth()
    # config_change: raise the (too-small) pool-size limit, not scale or rollback.
    assert truth.remediation_class == "config_change"
    assert truth.min_evidence_path == ["query_logs", "query_metrics"]
    assert truth.root_cause  # names the cause for the scorer; never shown to the agent


# --- determinism (invariant I3) -----------------------------------------------


def test_activate_is_deterministic_for_a_seed() -> None:
    assert_deterministic_activation(POOL_EXHAUSTION, SEED)


def test_activate_differs_across_seeds() -> None:
    assert_activation_varies_by_seed(POOL_EXHAUSTION)


# --- the core signal: pool saturation tracks the load peaks -------------------


def test_pool_saturates_exactly_when_load_peaks() -> None:
    store, _ = POOL_EXHAUSTION.activate(SEED)
    load = series_by_onset(store, AFFECTED_SERVICE, LOAD_METRIC, _WIDE)
    pool = series_by_onset(store, AFFECTED_SERVICE, POOL_METRIC, _WIDE)
    # The two series share their bucket windows, so they can be compared bucket-by-bucket.
    incident_buckets = sorted(onset for onset in load if onset >= T0)
    assert incident_buckets  # the incident is split into load buckets

    peaks = {
        onset
        for onset in incident_buckets
        if load[onset].p99 > load[onset].baseline * _LOAD_PEAK_FACTOR
    }
    saturated = {onset for onset in incident_buckets if pool[onset].p95 > _POOL_SATURATED_PCT}
    # Saturation coincides with the load peaks, bucket for bucket — the correlation.
    assert peaks == saturated
    # ...and it is intermittent: some buckets peak, some recover (not a single onset).
    assert 0 < len(peaks) < len(incident_buckets)
    # In a quiet bucket the pool sits at baseline, far from the ceiling.
    for onset in incident_buckets:
        if onset not in peaks:
            assert pool[onset].p95 < _POOL_SATURATED_PCT


def test_failures_cluster_in_the_saturation_windows() -> None:
    store, _ = POOL_EXHAUSTION.activate(SEED)
    pool = store.metric_series(AFFECTED_SERVICE, POOL_METRIC, _WIDE)
    saturated_windows = [s.anomaly_window for s in pool if s.p95 > _POOL_SATURATED_PCT]
    quiet_windows = [
        s.anomaly_window
        for s in pool
        if s.p95 <= _POOL_SATURATED_PCT and s.anomaly_window.start >= T0
    ]

    errors = error_logs(store, AFFECTED_SERVICE)
    assert errors  # the incident produces failures...
    # ...and every one falls inside a saturated bucket (failures track saturation),
    assert all(any(w.contains(e.timestamp) for w in saturated_windows) for e in errors)
    # ...while none falls in a quiet, recovered bucket — the intermittency is real.
    assert all(not any(w.contains(e.timestamp) for w in quiet_windows) for e in errors)


# --- the red herring: a recent deploy that does NOT correlate ------------------


def test_misleading_recent_deploy_predates_and_misaligns_with_failures() -> None:
    store, _ = POOL_EXHAUSTION.activate(SEED)
    deploys = store.deploys()
    assert len(deploys) == 1
    deploy = deploys[0]
    # On the alerting service and recent — exactly what tempts a reflexive rollback,
    assert deploy.service == AFFECTED_SERVICE
    assert deploy.timestamp < T0  # ...but it predates the incident, not coincident with it.
    # Its summary is benign: it never hints at the pool/load cause.
    assert "pool" not in deploy.summary.lower()
    assert "connection" not in deploy.summary.lower()

    # The failures do not coincide with the deploy: they begin at/after T0, and the
    # span between the deploy and the first failure is calm (a deploy regression would
    # have failed continuously from the deploy onward).
    errors = error_logs(store, AFFECTED_SERVICE)
    assert errors
    assert all(e.timestamp >= T0 for e in errors)
    calm_after_deploy = TimeRange(start=deploy.timestamp, end=T0)
    assert not error_logs(store, AFFECTED_SERVICE, calm_after_deploy)


# --- the alert states the symptom, not the cause ------------------------------


def test_alert_describes_symptom_not_cause() -> None:
    _, alert = POOL_EXHAUSTION.activate(SEED)
    assert_alert_states_symptom_not_cause(
        alert, service=AFFECTED_SERVICE, t0=T0, forbidden=["pool", "deploy"]
    )


# --- the eval-validity gate ---------------------------------------------------


def test_no_verbatim_leak() -> None:
    store, alert = POOL_EXHAUSTION.activate(SEED)
    assert_no_verbatim_leak(store, alert, POOL_EXHAUSTION.ground_truth())


def test_leak_guard_catches_a_planted_leak() -> None:
    store, alert = POOL_EXHAUSTION.activate(SEED)
    assert_leak_guard_detects_planted_leak(
        store, alert, POOL_EXHAUSTION.ground_truth(), service=AFFECTED_SERVICE, t0=T0
    )
