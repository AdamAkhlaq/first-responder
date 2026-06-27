"""Tests for the hidden answer key, GroundTruth (eval-only; invariant I2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from first_responder.schema.ground_truth import GroundTruth


def test_ground_truth_representative() -> None:
    truth = GroundTruth(
        root_cause="bad deploy of checkout v2.4.1 leaked connections",
        remediation_class="rollback",
        min_evidence_path=["query_deploys", "query_metrics"],
    )
    assert truth.remediation_class == "rollback"
    # The minimum path names the tools a correct run must touch.
    assert truth.min_evidence_path == ["query_deploys", "query_metrics"]


@pytest.mark.parametrize(
    "remediation_class",
    ["rollback", "scale", "config_change", "restart"],
)
def test_remediation_class_accepts_real_fixes(remediation_class: str) -> None:
    truth = GroundTruth(
        root_cause="x",
        remediation_class=remediation_class,  # type: ignore[arg-type]
        min_evidence_path=["query_logs"],
    )
    assert truth.remediation_class == remediation_class


def test_remediation_class_rejects_unknown() -> None:
    # "unknown" is the agent's honest-non-answer escape hatch; an answer key always
    # names a real fix, so it must not be a valid GroundTruth value.
    with pytest.raises(ValidationError):
        GroundTruth(
            root_cause="x",
            remediation_class="unknown",  # type: ignore[arg-type]
            min_evidence_path=["query_logs"],
        )


def test_min_evidence_path_required() -> None:
    with pytest.raises(ValidationError):
        GroundTruth(root_cause="x", remediation_class="rollback")  # type: ignore[call-arg]


def test_ground_truth_is_immutable() -> None:
    truth = GroundTruth(
        root_cause="x",
        remediation_class="rollback",
        min_evidence_path=["query_logs"],
    )
    with pytest.raises(ValidationError):
        truth.root_cause = "y"
