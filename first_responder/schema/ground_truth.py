"""The hidden answer key for a scenario — read only by the eval harness.

A :class:`GroundTruth` records what a correct diagnosis *should* reach for a
fault-injected scenario: the true root cause, the remediation class that resolves
it, and the minimum set of tools a run must touch to establish the answer.

This is the answer key, so it is fenced off by invariant I2: only the eval harness
(:mod:`first_responder.eval`) may read it, and only after a run has completed. The
agent's context is assembled without ever calling ``ground_truth()`` — if the
graded system could see this, the evaluation would measure nothing. That single
call site is the boundary keeping the agent blind to what it is graded against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from first_responder.schema.diagnosis import KnownRemediationClass


class GroundTruth(BaseModel):
    """The correct answer for one scenario: cause, fix class, and required tools.

    ``min_evidence_path`` names the tools a correct run must touch — the shortest
    chain of observations that actually establishes the cause (correlating a deploy
    against a latency spike, for instance, needs both ``query_deploys`` and
    ``query_metrics``). The scorer reads it to grade evidence-path coverage: did
    the run reach its answer through the signal that proves it, or arrive there by
    luck?

    ``remediation_class`` excludes ``"unknown"`` — an answer key always names a
    real fix, whereas ``"unknown"`` is reserved for the agent's honest non-answer.
    """

    model_config = ConfigDict(frozen=True)

    root_cause: str
    remediation_class: KnownRemediationClass
    min_evidence_path: list[str]
