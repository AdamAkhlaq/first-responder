"""Tests for the scenario-relative time primitives."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from first_responder.schema.time import TimeRange


def test_duration() -> None:
    assert TimeRange(start=-30, end=60).duration == 90
    assert TimeRange(start=10, end=10).duration == 0  # empty window is valid


def test_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start=10, end=5)


def test_contains_is_half_open() -> None:
    window = TimeRange(start=0, end=60)
    assert window.contains(0)  # start is inclusive
    assert not window.contains(60)  # end is exclusive
    assert window.contains(59)
    assert window.contains(30)
    assert not window.contains(-1)
    assert not window.contains(61)


def test_overlaps() -> None:
    a = TimeRange(start=0, end=60)
    assert a.overlaps(TimeRange(start=30, end=90))  # partial
    assert a.overlaps(TimeRange(start=-30, end=120))  # a inside other
    assert a.overlaps(TimeRange(start=10, end=20))  # other inside a
    assert a.overlaps(TimeRange(start=59, end=90))  # share the instant [59, 60)
    assert not a.overlaps(TimeRange(start=60, end=90))  # abutting windows tile, no overlap
    assert not a.overlaps(TimeRange(start=-30, end=0))  # abutting before, no overlap
    assert not a.overlaps(TimeRange(start=61, end=90))  # disjoint after


def test_overlaps_is_symmetric() -> None:
    a = TimeRange(start=0, end=60)
    overlapping = TimeRange(start=30, end=90)
    disjoint = TimeRange(start=60, end=90)
    assert a.overlaps(overlapping) and overlapping.overlaps(a)
    assert not a.overlaps(disjoint) and not disjoint.overlaps(a)


def test_around_builds_window_about_reference() -> None:
    window = TimeRange.around(120, before=30, after=15)
    assert (window.start, window.end) == (90, 135)
    assert window.contains(120)


def test_since_builds_forward_window() -> None:
    window = TimeRange.since(120, delta=60)
    assert (window.start, window.end) == (120, 180)
    assert window.duration == 60


def test_is_immutable() -> None:
    window = TimeRange(start=0, end=10)
    with pytest.raises(ValidationError):
        window.start = 5
