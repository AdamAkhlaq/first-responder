"""Telemetry models — the agent's perception of the world.

These are the typed values the five tools return (``query_logs``,
``query_metrics``, ``get_traces``, ``query_deploys``, ``search_runbooks``). They
are the *only* shape in which the agent ever sees telemetry, so their granularity
is a deliberate product decision, not an implementation detail (ADR-002).

Every timestamp here is :data:`~first_responder.schema.time.Seconds` — integer
seconds relative to the scenario incident origin T0 (there is no real clock; see
:mod:`first_responder.schema.time`). All models are frozen value objects: a tool
returns an observation, and an observation does not change after it is made.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from first_responder.schema.time import Seconds, TimeRange

LogLevel = Literal["debug", "info", "warn", "error"]
SpanStatus = Literal["ok", "error"]


class LogEntry(BaseModel):
    """A single structured log line emitted by a service.

    ``request_id`` is the seam that joins a log line to a :class:`Trace`, letting
    the agent pivot from a symptom in the logs to the trace that produced it.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: Seconds
    service: str
    level: LogLevel
    message: str
    fields: dict[str, JsonValue] = Field(default_factory=dict)
    request_id: str | None = None


class MetricSeries(BaseModel):
    """A metric summarised over an anomaly window — *not* a list of raw points.

    The tool layer projects a raw series down to ``baseline`` plus the p50/p95/p99
    percentiles over ``anomaly_window`` and returns only that. This is the
    granularity decision ADR-002 calls out: raw points would flood the agent's
    finite context with noise, so the tool hands back the *shape* a human
    diagnostician actually reads — a baseline to compare against and the tail
    behaviour during the incident. The cost is that summarisation bakes judgment
    into the tool, so the summary must preserve the signal (a spike shows up as
    p95/p99 well above ``baseline``).
    """

    model_config = ConfigDict(frozen=True)

    service: str
    metric: str
    unit: str
    baseline: float
    anomaly_window: TimeRange
    p50: float
    p95: float
    p99: float

    @model_validator(mode="after")
    def _check_percentile_order(self) -> MetricSeries:
        if not self.p50 <= self.p95 <= self.p99:
            raise ValueError(
                f"percentiles must be non-decreasing, got "
                f"p50={self.p50}, p95={self.p95}, p99={self.p99}"
            )
        return self


class Span(BaseModel):
    """One operation within a trace.

    ``span_id`` and ``parent_span_id`` form the edges of the trace tree: the child
    of span X is the span whose ``parent_span_id == X.span_id``. That edge is how
    the agent follows a request one hop downstream (service A → service B) to find
    where latency or errors actually originate. The root span has no parent.
    """

    model_config = ConfigDict(frozen=True)

    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    start: Seconds
    end: Seconds
    status: SpanStatus

    @property
    def duration(self) -> Seconds:
        """How long the operation took, in seconds (``end - start``)."""
        return self.end - self.start

    @model_validator(mode="after")
    def _check_order(self) -> Span:
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self


class Trace(BaseModel):
    """One request's path through the system: a ``request_id`` and its spans.

    Spans are ordered by start time. A trace carries enough structure — the
    parent/child span edges and per-span timing — to follow a single downstream
    hop and read where a request spent its time.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    spans: list[Span]


class DeployEvent(BaseModel):
    """A deployment of a new version of a service.

    The agent correlates ``timestamp`` against a symptom onset: a deploy landing
    at the same instant an error rate jumps is the event-correlation signal behind
    the ``bad_deploy`` scenario.
    """

    model_config = ConfigDict(frozen=True)

    timestamp: Seconds
    service: str
    version: str
    summary: str


class RunbookChunk(BaseModel):
    """A retrieved chunk of operational documentation.

    ``relevance`` is the retrieval score assigned by ``search_runbooks`` for a
    given query; a chunk sitting in the corpus before any search has no score, so
    the field defaults to ``None`` and is populated at retrieval time.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    source: str
    text: str
    relevance: float | None = None
