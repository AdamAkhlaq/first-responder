"""Concrete fault scenarios. Importing this package registers every scenario.

Each scenario module self-registers in the scenario registry at import time, so a
single ``import first_responder.simulator.scenarios`` makes them all resolvable by
name through :func:`first_responder.simulator.scenario.get_scenario`.
"""

from first_responder.simulator.scenarios import bad_deploy, cascading_timeout, pool_exhaustion

__all__ = ["bad_deploy", "cascading_timeout", "pool_exhaustion"]
