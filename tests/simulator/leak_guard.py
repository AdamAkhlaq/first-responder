"""Shared eval-validity gate: a scenario must never state its own answer in signal.

:func:`assert_no_verbatim_leak` scans every agent-visible string a scenario emits —
the alert text, log messages, and deploy summaries — and fails if the ground-truth
root cause appears verbatim. A scenario that hands the agent its own conclusion
measures retrieval, not reasoning, so every scenario's tests run this guard
(ARCHITECTURE: scenario acceptance requires the verdict is never present verbatim
in agent-visible signal).
"""

from __future__ import annotations

from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.simulator.store import TelemetryStore


def agent_visible_text(store: TelemetryStore, alert: Alert) -> list[str]:
    """Every free-text string the agent could read back through the tools.

    Reads the store's whole contents rather than a service-scoped slice: the agent
    can query any service or window, so nothing in the store is hidden from it.
    (Reaches into the store's collections directly — this is test-only support, not
    production code, so it is fine to bypass the scoped reader API here.)
    """
    texts = [alert.symptom, alert.service]
    for entry in store._logs:  # one pass over the logs: message and any field values
        texts.append(entry.message)
        texts.extend(str(value) for value in entry.fields.values())
    texts.extend(deploy.summary for deploy in store._deploys)
    return texts


def assert_no_verbatim_leak(store: TelemetryStore, alert: Alert, ground_truth: GroundTruth) -> None:
    """Fail if the ground-truth root cause appears verbatim in any agent-visible string."""
    needle = ground_truth.root_cause.lower()
    for text in agent_visible_text(store, alert):
        assert needle not in text.lower(), (
            f"eval-validity gate: ground-truth root cause leaked verbatim into "
            f"agent-visible text: {text!r}"
        )
