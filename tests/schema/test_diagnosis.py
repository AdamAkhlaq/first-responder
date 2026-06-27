"""Tests for the agent's output contract: Evidence and Diagnosis."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from first_responder.schema.diagnosis import Diagnosis, Evidence

# --- representative instances -------------------------------------------------


def test_diagnosis_representative() -> None:
    evidence = Evidence(
        tool="query_deploys",
        query={"service": "checkout", "window": {"start": -300, "end": 60}},
        finding="checkout v2.4.1 deployed 12s before the error rate jumped",
    )
    diagnosis = Diagnosis(
        root_cause="bad deploy of checkout v2.4.1 leaked connections",
        confidence="high",
        evidence=[evidence],
        proposed_fix="roll checkout back to v2.4.0",
        remediation_class="rollback",
    )
    assert diagnosis.confidence == "high"
    # Every claim traces to the tool call that produced it (I4).
    assert diagnosis.evidence[0].tool == "query_deploys"
    assert diagnosis.evidence[0].query["service"] == "checkout"


def test_honest_non_answer_is_valid() -> None:
    # Low confidence with no evidence is the honest "I can't tell" — a valid,
    # scored outcome, not an error.
    diagnosis = Diagnosis(
        root_cause="undetermined: the signal did not isolate a single cause",
        confidence="low",
        evidence=[],
        proposed_fix="gather more signal before acting",
        remediation_class="unknown",
    )
    assert diagnosis.confidence == "low"
    assert diagnosis.evidence == []
    assert diagnosis.remediation_class == "unknown"


def test_evidence_defaults_to_empty() -> None:
    # An evidence-free diagnosis is structurally valid (it underwrites the honest
    # non-answer), so the field is optional and defaults to an empty list.
    diagnosis = Diagnosis(
        root_cause="undetermined",
        confidence="low",
        proposed_fix="none",
        remediation_class="unknown",
    )
    assert diagnosis.evidence == []


# --- enum / contract validation -----------------------------------------------


@pytest.mark.parametrize("confidence", ["high", "medium", "low"])
def test_confidence_accepts_known_levels(confidence: str) -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence=confidence,  # type: ignore[arg-type]
        proposed_fix="y",
        remediation_class="restart",
    )
    assert diagnosis.confidence == confidence


def test_confidence_rejects_unknown_level() -> None:
    with pytest.raises(ValidationError):
        Diagnosis(
            root_cause="x",
            confidence="certain",  # type: ignore[arg-type]
            proposed_fix="y",
            remediation_class="restart",
        )


@pytest.mark.parametrize(
    "remediation_class",
    ["rollback", "scale", "config_change", "restart", "unknown"],
)
def test_remediation_class_accepts_known_values(remediation_class: str) -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence="medium",
        proposed_fix="y",
        remediation_class=remediation_class,  # type: ignore[arg-type]
    )
    assert diagnosis.remediation_class == remediation_class


def test_remediation_class_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Diagnosis(
            root_cause="x",
            confidence="medium",
            proposed_fix="y",
            remediation_class="reboot",  # type: ignore[arg-type]
        )


def test_missing_required_field_rejected() -> None:
    with pytest.raises(ValidationError):
        Diagnosis(
            root_cause="x",
            confidence="low",
            proposed_fix="y",
        )  # type: ignore[call-arg]  # no remediation_class


def test_models_are_immutable() -> None:
    diagnosis = Diagnosis(
        root_cause="x",
        confidence="low",
        proposed_fix="y",
        remediation_class="unknown",
    )
    evidence = Evidence(tool="query_logs", query={"service": "a"}, finding="f")
    with pytest.raises(ValidationError):
        diagnosis.confidence = "high"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        evidence.finding = "g"
