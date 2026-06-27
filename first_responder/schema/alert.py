"""The incident alert — the single input the agent receives to start a run.

An :class:`Alert` is the entire starting context for a diagnosis: the agent gets
one and nothing else, then must reason from symptom to cause through the tools. It
lives with the contracts (not the simulator) because it is part of the agent↔world
interface — a real alerting system would hand the agent the same shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from first_responder.schema.time import Seconds


class Alert(BaseModel):
    """What fired, on which service, and when — relative to the incident origin T0.

    ``symptom`` is the *observable* that tripped the alert ("error rate above
    threshold", "p99 latency elevated"), never the cause. Stating the cause here
    would let the agent read the answer instead of inferring it, so keeping the
    symptom causally upstream of the fault is part of every scenario's acceptance
    gate. ``fired_at`` is scenario-relative seconds from T0 (see
    :mod:`first_responder.schema.time`).
    """

    model_config = ConfigDict(frozen=True)

    service: str
    symptom: str
    fired_at: Seconds
