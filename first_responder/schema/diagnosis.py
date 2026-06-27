"""The agent's output contract: a structured, evidence-backed root-cause Diagnosis.

A :class:`Diagnosis` is the single value the reason-act loop emits. Every claim it
makes is traceable: each :class:`Evidence` entry cites the tool result that
supports it, so any conclusion can be walked back to the observations that justify
it (invariant I4). A correct ``root_cause`` backed by evidence that does not trace
to real tool results is, by that invariant, not a clean answer.

Honesty is a first-class outcome. A ``Diagnosis`` with ``confidence="low"`` and an
empty ``evidence`` list is a deliberate, valid construction — the agent's way of
saying "the signal did not support a conclusion." An honest non-answer is
preferable to a confident guess and is scored as a legitimate outcome, not an
error.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

Confidence = Literal["high", "medium", "low"]

# The real remediation shapes a fix can take. These are the single source of truth
# for the remediation vocabulary: a scenario's GroundTruth is drawn from exactly
# this set (an answer key always names a real fix).
KnownRemediationClass = Literal["rollback", "scale", "config_change", "restart"]

# What the agent may propose: a real fix, or "unknown" — the honest escape hatch
# when evidence names a cause without implying a single remediation. The scorer
# matches the real classes loosely against the scenario's known class.
RemediationClass = Literal[KnownRemediationClass, "unknown"]


class Evidence(BaseModel):
    """One link in the chain from a tool result to a claim in the diagnosis.

    ``tool`` and ``query`` identify the exact call that produced an observation and
    ``finding`` records what that observation established. Together they make a
    claim traceable back to a real tool result (invariant I4): the scorer can
    confirm the cited call actually ran and returned what is claimed, so a verdict
    cannot rest on fabricated justification.
    """

    model_config = ConfigDict(frozen=True)

    tool: str
    query: dict[str, JsonValue]
    finding: str


class Diagnosis(BaseModel):
    """The agent's verdict on an incident: a root cause, its evidence, and a fix.

    The reason-act loop emits exactly one of these. ``evidence`` is the trail that
    justifies ``root_cause`` — each entry cites the tool result behind a claim, so
    the conclusion traces end-to-end back to observations (invariant I4).
    ``remediation_class`` is the scoreable projection of the free-text
    ``proposed_fix``.

    A low-confidence instance with empty ``evidence`` is a valid, deliberate
    construction: the honest non-answer the agent returns when the signal does not
    isolate a cause. It is preferable to a confident guess and is scored as a
    legitimate outcome rather than treated as an error.
    """

    model_config = ConfigDict(frozen=True)

    root_cause: str
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    proposed_fix: str
    remediation_class: RemediationClass
