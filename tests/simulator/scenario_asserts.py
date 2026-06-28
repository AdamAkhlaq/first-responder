"""Shared assertions and helpers for the scenario test suite.

The three scenario test files (``bad_deploy``, ``cascading_timeout``,
``pool_exhaustion``) all check the same scenario-agnostic contracts:
determinism (invariant I3), a fresh store per activation, telemetry that varies
across seeds, and an alert that states a symptom and never the cause. Those
checks live here once so every scenario verifies them identically and a new
scenario inherits them for free — only the scenario-specific signal (the
correlation, the red herring) stays in the per-scenario file.
"""

from __future__ import annotations

from collections.abc import Sequence

from first_responder.schema.alert import Alert
from first_responder.schema.telemetry import LogEntry, MetricSeries
from first_responder.schema.time import Seconds, TimeRange
from first_responder.simulator.scenario import Scenario
from first_responder.simulator.store import TelemetryStore


def _snapshot(store: TelemetryStore) -> tuple[object, ...]:
    """A value-comparable snapshot of everything a store holds.

    Reaches into the store's collections directly (test-only support, as in
    :mod:`tests.simulator.leak_guard`): the frozen telemetry models compare by
    value, so two snapshots are equal iff the stores hold identical telemetry.
    """
    return (store._logs, store._metric_series, store._traces, store._deploys)


def assert_deterministic_activation(scenario: Scenario, seed: int) -> None:
    """Same seed ⇒ identical telemetry returned in a fresh store each call (invariant I3)."""
    first_store, first_alert = scenario.activate(seed)
    second_store, second_alert = scenario.activate(seed)
    assert first_store is not second_store  # a fresh store per call — runs never share state
    assert _snapshot(first_store) == _snapshot(second_store)
    assert first_alert == second_alert


def assert_activation_varies_by_seed(scenario: Scenario, seed_a: int = 1, seed_b: int = 2) -> None:
    """Different seeds ⇒ different (but valid) telemetry — rendering is seeded, not fixed."""
    first_store, _ = scenario.activate(seed_a)
    second_store, _ = scenario.activate(seed_b)
    assert _snapshot(first_store) != _snapshot(second_store)


def assert_alert_states_symptom_not_cause(
    alert: Alert, *, service: str, t0: Seconds, forbidden: Sequence[str]
) -> None:
    """The alert names the symptom on ``service`` after T0 and no ``forbidden`` cause term."""
    assert alert.service == service
    assert alert.fired_at >= t0
    symptom = alert.symptom.lower()
    for term in forbidden:
        assert term.lower() not in symptom


def series_by_onset(
    store: TelemetryStore, service: str, metric: str, window: TimeRange
) -> dict[Seconds, MetricSeries]:
    """The service's ``metric`` series in ``window``, keyed by anomaly-window start (its bucket)."""
    return {s.anomaly_window.start: s for s in store.metric_series(service, metric, window)}


def error_logs(
    store: TelemetryStore, service: str, window: TimeRange | None = None
) -> list[LogEntry]:
    """Every error-level log for ``service`` (optionally narrowed to ``window``)."""
    return store.logs_for(service, window, filter=lambda e: e.level == "error")
