"""Scenario-relative time primitives.

Time is expressed as **integer seconds relative to a scenario's incident origin,
T0**: T0 is ``t = 0``, negative offsets are before the incident, positive offsets
after it. There is no real-world clock anywhere in the system — only offsets
from T0.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

# Why scenario-relative rather than wall-clock time: telemetry must be a pure
# function of (fault, seed) so every run is reproducible (invariant I3). A real
# `now` would make two runs of the same scenario diverge and would rot stored
# fixtures over time. Pinning time to T0 removes that source of non-determinism.

# Integer seconds measured from the incident origin T0 (see module docstring).
Seconds = int


class TimeRange(BaseModel):
    """A half-open interval ``[start, end)`` of scenario time, in seconds from T0.

    The start is inclusive and the end is exclusive. That is what lets adjacent
    windows tile cleanly: a record at exactly ``t = end`` belongs to the next
    window, not to two at once — so a baseline window and the anomaly window that
    begins where it ends never double-count a boundary record. Instances are
    immutable value objects.
    """

    model_config = ConfigDict(frozen=True)

    start: Seconds
    end: Seconds

    @model_validator(mode="after")
    def _check_order(self) -> TimeRange:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self

    @property
    def duration(self) -> Seconds:
        """Length of the interval in seconds (``end - start``)."""
        return self.end - self.start

    def contains(self, ts: Seconds) -> bool:
        """Whether ``ts`` falls within the half-open interval (``start <= ts < end``)."""
        return self.start <= ts < self.end

    def overlaps(self, other: TimeRange) -> bool:
        """Whether this interval shares any instant with ``other``."""
        return self.start < other.end and other.start < self.end

    @classmethod
    def around(cls, ref: Seconds, before: Seconds, after: Seconds) -> TimeRange:
        """Window from ``before`` seconds before ``ref`` to ``after`` seconds after it.

        ``ref`` is any reference point in scenario time — often the incident
        origin T0, but an event timestamp (e.g. a deploy) works just as well.
        """
        return cls(start=ref - before, end=ref + after)

    @classmethod
    def since(cls, ref: Seconds, delta: Seconds) -> TimeRange:
        """Window of length ``delta`` starting at ``ref`` (``[ref, ref + delta)``)."""
        return cls(start=ref, end=ref + delta)
