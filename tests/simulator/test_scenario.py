"""Tests for the Scenario abstraction, its registry, and activate() determinism."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import first_responder.simulator.scenario as scenario_module
from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.schema.time import TimeRange
from first_responder.simulator.render import render_log_stream, seeded_rng
from first_responder.simulator.scenario import (
    Scenario,
    all_scenarios,
    get_scenario,
    register,
    scenario_names,
)
from first_responder.simulator.store import TelemetryStore


class _FakeScenario(Scenario):
    """A minimal Scenario whose telemetry is rendered purely from the seed."""

    def __init__(self, name: str = "fake") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def activate(self, seed: int) -> tuple[TelemetryStore, Alert]:
        store = TelemetryStore()
        store.add_logs(
            render_log_stream(
                seeded_rng(seed), service="svc", window=TimeRange(start=0, end=120), count=6
            )
        )
        return store, Alert(service="svc", symptom="error rate elevated", fired_at=0)

    def ground_truth(self) -> GroundTruth:
        return GroundTruth(
            root_cause="x", remediation_class="restart", min_evidence_path=["query_logs"]
        )


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    # Run each test against an empty registry, then restore the original — so a
    # self-registering scenario imported elsewhere can't perturb these
    # order-sensitive assertions, and these tests don't leak their fakes either.
    saved = dict(scenario_module._REGISTRY)
    scenario_module._REGISTRY.clear()
    try:
        yield
    finally:
        scenario_module._REGISTRY.clear()
        scenario_module._REGISTRY.update(saved)


# --- the abstraction ----------------------------------------------------------


def test_incomplete_scenario_cannot_be_instantiated() -> None:
    class Incomplete(Scenario):
        @property
        def name(self) -> str:
            return "incomplete"

        # activate / ground_truth deliberately unimplemented

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


# --- the registry -------------------------------------------------------------


def test_register_and_resolve() -> None:
    fake = _FakeScenario("alpha")
    assert register(fake) is fake  # returns it for inline binding
    assert get_scenario("alpha") is fake
    assert "alpha" in scenario_names()
    assert fake in all_scenarios()


def test_register_rejects_duplicate_name() -> None:
    register(_FakeScenario("dup"))
    with pytest.raises(ValueError, match="already registered"):
        register(_FakeScenario("dup"))


def test_get_unknown_scenario_raises() -> None:
    with pytest.raises(KeyError):
        get_scenario("does-not-exist")


def test_registry_preserves_registration_order() -> None:
    register(_FakeScenario("first"))
    register(_FakeScenario("second"))
    assert scenario_names() == ["first", "second"]


# --- activate() determinism ---------------------------------------------------


def test_activate_is_deterministic_for_a_seed() -> None:
    scenario = _FakeScenario()
    store_a, alert_a = scenario.activate(42)
    store_b, alert_b = scenario.activate(42)
    assert store_a.logs_for("svc") == store_b.logs_for("svc")
    assert alert_a == alert_b


def test_activate_differs_across_seeds() -> None:
    scenario = _FakeScenario()
    store_one, _ = scenario.activate(1)
    store_two, _ = scenario.activate(2)
    assert store_one.logs_for("svc") != store_two.logs_for("svc")


def test_activate_returns_a_fresh_store_each_call() -> None:
    scenario = _FakeScenario()
    store_a, _ = scenario.activate(1)
    store_b, _ = scenario.activate(1)
    assert store_a is not store_b
