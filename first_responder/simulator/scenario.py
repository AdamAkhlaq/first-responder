"""The Scenario abstraction and registry — the unit the eval harness runs.

A :class:`Scenario` owns a fault and knows three things about it: its ``name``, how
to ``activate`` it into agent-visible telemetry, and its hidden ``ground_truth``.
``activate`` and ``ground_truth`` are the two halves of the simulator contract that
:doc:`ARCHITECTURE` names — one emits signal, the other the answer key, and they
never meet except in the scorer.

The module also holds the registry mapping ``name -> Scenario`` instance. Concrete
scenarios register themselves here so the CLI and eval harness can resolve them by
name; this module stays empty of any concrete fault.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.simulator.store import TelemetryStore


class Scenario(ABC):
    """A fault-injection scenario: signal on one side, ground truth on the other.

    Implementations must render telemetry as a pure function of ``(fault, seed)``
    (invariant I3): every stochastic choice draws from
    :func:`~first_responder.simulator.render.seeded_rng`, so the same scenario and
    seed reproduce identical telemetry. The rendered signal must never state the
    cause verbatim — the agent has to infer it.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this scenario (registry key and report label)."""

    @abstractmethod
    def activate(self, seed: int) -> tuple[TelemetryStore, Alert]:
        """Render the fault into a fresh, populated store and the alert that fired.

        Returns a new :class:`~first_responder.simulator.store.TelemetryStore` each
        call (so runs never share state) together with the triggering
        :class:`~first_responder.schema.alert.Alert` — the agent's only input.
        """

    @abstractmethod
    def ground_truth(self) -> GroundTruth:
        """The hidden answer key — read only by the eval harness, after a run (I2)."""


_REGISTRY: dict[str, Scenario] = {}


def register(scenario: Scenario) -> Scenario:
    """Register ``scenario`` under its name and return it (so it can be bound inline).

    Names are unique identifiers used by the CLI and the eval report, so a
    duplicate name is a programming error and is rejected.
    """
    if scenario.name in _REGISTRY:
        raise ValueError(f"scenario {scenario.name!r} is already registered")
    _REGISTRY[scenario.name] = scenario
    return scenario


def get_scenario(name: str) -> Scenario:
    """Resolve a registered scenario by name (raises :class:`KeyError` if unknown)."""
    return _REGISTRY[name]


def all_scenarios() -> list[Scenario]:
    """Every registered scenario, in registration order."""
    return list(_REGISTRY.values())


def scenario_names() -> list[str]:
    """The names of all registered scenarios, in registration order."""
    return list(_REGISTRY)
