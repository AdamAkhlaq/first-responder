"""The ``cascading_timeout`` scenario: A's timeouts caused by a downstream B spike.

Reasoning mode: **spatial / trace-following**. The alert fires on service A (5xx and
latency), but A is healthy — its own resource metrics are flat. The cause is one
hop downstream: service B's latency spikes at T0, and A's requests stall on B until
they time out. Solving it means connecting three signals: A's timeout *logs* (the
symptom) → a *trace* whose A→B hop shows B's span eating almost all the request
time → B's *metric* spiking at T0. That cross-signal path is exactly
``min_evidence_path = [query_logs, get_traces, query_metrics]``.

The timeout logs name no downstream service, so the agent cannot shortcut to B from
the logs alone — it must follow the trace hop. The planted red herring is that A's
own health (CPU) looks normal, so a naive reading that blames the alerting service
is wrong. No agent-visible string states the cause (the eval-validity gate enforced
by ``assert_no_verbatim_leak``).
"""

from __future__ import annotations

from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.schema.telemetry import Trace
from first_responder.schema.time import Seconds, TimeRange
from first_responder.simulator.render import (
    jitter,
    render_flat_then_spike,
    render_log_stream,
    render_metric_series,
    render_trace_chain,
    seeded_rng,
)
from first_responder.simulator.scenario import Scenario, register
from first_responder.simulator.store import TelemetryStore

# Incident origin and the two services on the trace path.
T0: Seconds = 0
AFFECTED_SERVICE = "api-gateway"  # service A — where the alert fires (the symptom).
DOWNSTREAM_SERVICE = "payments"  # service B — the true cause, one trace hop away.

# Shape of the incident.
_WINDOW: Seconds = 300
_ALERT_LAG: Seconds = 60
_PRE_WINDOW = TimeRange(start=T0 - _WINDOW, end=T0)
_INCIDENT_WINDOW = TimeRange.since(T0, _WINDOW)
_LOG_COUNT = 6
_TRACE_COUNT = 4
_A_DURATION: Seconds = 30  # A's request budget — it times out around here.
_B_SLOW_DURATION: Seconds = 26  # B consumes almost all of A's time — the bottleneck.
_B_LATENCY_BASELINE_MS = 40.0
_B_LATENCY_SPIKE = 15.0  # B's latency jumps sharply at T0.
_A_CPU_BASELINE = 35.0  # A's own CPU — stays healthy across the incident (red herring).

# Agent-visible text. The timeout log names no downstream service (the agent must
# follow the trace to find B); none of it states the cause.
_TIMEOUT_LOG_MESSAGE = "downstream call timed out after 30s"
_ALERT_SYMPTOM = f"5xx rate and latency for {AFFECTED_SERVICE} breached SLO"

# The hidden answer key — never present verbatim in any signal above.
_ROOT_CAUSE = (
    f"the downstream {DOWNSTREAM_SERVICE} service saturated and its latency spiked at T0, "
    f"stalling {AFFECTED_SERVICE} requests until they timed out"
)


class CascadingTimeout(Scenario):
    """A downstream latency spike that times out the upstream — diagnosed by trace hop."""

    @property
    def name(self) -> str:
        return "cascading_timeout"

    def activate(self, seed: int) -> tuple[TelemetryStore, Alert]:
        rng = seeded_rng(seed)
        store = TelemetryStore()

        # Service A's symptom: request timeouts around T0, healthy before it.
        store.add_logs(
            render_log_stream(
                rng,
                service=AFFECTED_SERVICE,
                window=_INCIDENT_WINDOW,
                count=_LOG_COUNT,
                level="error",
                message=_TIMEOUT_LOG_MESSAGE,
            )
        )
        store.add_logs(
            render_log_stream(
                rng,
                service=AFFECTED_SERVICE,
                window=_PRE_WINDOW,
                count=_LOG_COUNT,
                level="info",
                message="request handled",
            )
        )

        # Traces: each request hops A -> B, and B's span dominates the latency, so
        # following the single hop reveals B as the bottleneck.
        traces: list[Trace] = []
        for index in range(_TRACE_COUNT):
            b_duration = round(jitter(rng, _B_SLOW_DURATION, fraction=0.1))
            start = T0 + rng.randrange(_WINDOW)
            traces.append(
                render_trace_chain(
                    rng,
                    request_id=f"req-{index}",
                    services=[AFFECTED_SERVICE, DOWNSTREAM_SERVICE],
                    start=start,
                    durations=[_A_DURATION, b_duration],
                    error_from=0,  # the timeout propagates up: both spans error.
                )
            )
        store.add_traces(traces)

        # B's latency: flat before T0, sharp spike at the onset — the real cause.
        store.add_metric_series(
            render_flat_then_spike(
                rng,
                service=DOWNSTREAM_SERVICE,
                metric="latency_ms",
                unit="ms",
                baseline=_B_LATENCY_BASELINE_MS,
                baseline_window=_PRE_WINDOW,
                anomaly_window=_INCIDENT_WINDOW,
                spike=_B_LATENCY_SPIKE,
            )
        )

        # Red herring: A's own CPU stays healthy across the incident, so blaming the
        # alerting service is wrong — the cause is downstream.
        store.add_metric_series(
            [
                render_metric_series(
                    rng,
                    service=AFFECTED_SERVICE,
                    metric="cpu_utilization",
                    unit="percent",
                    baseline=_A_CPU_BASELINE,
                    anomaly_window=_INCIDENT_WINDOW,
                    spike=1.0,
                )
            ]
        )

        alert = Alert(service=AFFECTED_SERVICE, symptom=_ALERT_SYMPTOM, fired_at=T0 + _ALERT_LAG)
        return store, alert

    def ground_truth(self) -> GroundTruth:
        # remediation_class="scale": B's latency climbs because it is saturated —
        # demand outstripped its capacity, a resource problem, so the fix is to add
        # capacity / scale B out. It is not "config_change": no setting is wrong, B
        # just needs more headroom. (A mis-set timeout or pool size would be a
        # config_change; that is not the fault injected here.)
        return GroundTruth(
            root_cause=_ROOT_CAUSE,
            remediation_class="scale",
            min_evidence_path=["query_logs", "get_traces", "query_metrics"],
        )


CASCADING_TIMEOUT = register(CascadingTimeout())
