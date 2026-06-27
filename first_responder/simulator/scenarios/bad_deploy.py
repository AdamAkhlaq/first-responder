"""The ``bad_deploy`` scenario: a sharp error-rate onset that coincides with a deploy.

Reasoning mode: **event correlation**. At T0 the affected service's error rate
jumps from a flat baseline to a sharp spike, and a deploy of that same service
lands at the same instant. The cause is inferable purely from the *coincidence of
timestamps* — the agent should pull metrics (see the spike onset), pull deploys
(see the deploy at the same time), and correlate. No log line names the deploy as
the cause; stating it would let the agent read the answer rather than reason to it
(the eval-validity gate enforced by ``assert_no_verbatim_leak``).

The planted red herring is a benign latency wobble on an *unrelated* service with
no deploy behind it — a coincidence the agent must rule out because nothing
correlates it with the symptom.
"""

from __future__ import annotations

from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.schema.telemetry import DeployEvent
from first_responder.schema.time import Seconds, TimeRange
from first_responder.simulator.render import (
    render_flat_then_spike,
    render_log_stream,
    render_metric_series,
    seeded_rng,
)
from first_responder.simulator.scenario import Scenario, register
from first_responder.simulator.store import TelemetryStore

# Incident origin and the services in play.
T0: Seconds = 0
AFFECTED_SERVICE = "checkout"
UNRELATED_SERVICE = "search"
DEPLOY_VERSION = "v2.4.1"

# Shape of the incident.
_WINDOW: Seconds = 300  # the baseline window and the anomaly window are each 5 min.
_ALERT_LAG: Seconds = 45  # detection lag between the onset at T0 and the alert firing.
_PRE_WINDOW = TimeRange(start=T0 - _WINDOW, end=T0)
_INCIDENT_WINDOW = TimeRange.since(T0, _WINDOW)
_BASELINE_ERROR_RATE = 0.4  # errors/s, the flat pre-incident level.
_ERROR_SPIKE = 30.0  # multiplier that turns the baseline into a sharp onset.
_HERRING_BASELINE_MS = 120.0
_HERRING_WOBBLE = 1.5  # a mild, benign blip — not a sharp spike.
_LOG_COUNT = 6

# Agent-visible text. None of it names the deploy as the cause (eval-validity gate);
# a real deploy summary describes the change, and error logs describe the symptom.
_DEPLOY_SUMMARY = f"{AFFECTED_SERVICE} {DEPLOY_VERSION}: switch payment client to async pool"
_ERROR_LOG_MESSAGE = "HTTP 500 returned to caller"
_ALERT_SYMPTOM = f"error rate for {AFFECTED_SERVICE} exceeded its alerting threshold"

# The hidden answer key — never present verbatim in any signal above.
_ROOT_CAUSE = (
    f"the {AFFECTED_SERVICE} {DEPLOY_VERSION} deploy at T0 regressed the request path "
    f"and drove the error-rate spike"
)


class BadDeploy(Scenario):
    """A deploy at T0 that spikes the error rate — diagnosable by event correlation."""

    @property
    def name(self) -> str:
        return "bad_deploy"

    def activate(self, seed: int) -> tuple[TelemetryStore, Alert]:
        rng = seeded_rng(seed)
        store = TelemetryStore()

        # Error rate: flat at baseline before T0, then a sharp spike at the onset.
        store.add_metric_series(
            render_flat_then_spike(
                rng,
                service=AFFECTED_SERVICE,
                metric="error_rate",
                unit="errors/s",
                baseline=_BASELINE_ERROR_RATE,
                baseline_window=_PRE_WINDOW,
                anomaly_window=_INCIDENT_WINDOW,
                spike=_ERROR_SPIKE,
            )
        )

        # The deploy that lands exactly at the onset — the cause to be inferred.
        store.add_deploys(
            [
                DeployEvent(
                    timestamp=T0,
                    service=AFFECTED_SERVICE,
                    version=DEPLOY_VERSION,
                    summary=_DEPLOY_SUMMARY,
                )
            ]
        )

        # Red herring: a benign latency wobble on an unrelated service, with no
        # deploy to correlate it — a coincidence the agent must rule out.
        store.add_metric_series(
            [
                render_metric_series(
                    rng,
                    service=UNRELATED_SERVICE,
                    metric="latency_ms",
                    unit="ms",
                    baseline=_HERRING_BASELINE_MS,
                    anomaly_window=_INCIDENT_WINDOW,
                    spike=_HERRING_WOBBLE,
                )
            ]
        )

        # Corroborating logs: healthy before the onset, errors after it.
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
        store.add_logs(
            render_log_stream(
                rng,
                service=AFFECTED_SERVICE,
                window=_INCIDENT_WINDOW,
                count=_LOG_COUNT,
                level="error",
                message=_ERROR_LOG_MESSAGE,
            )
        )

        alert = Alert(service=AFFECTED_SERVICE, symptom=_ALERT_SYMPTOM, fired_at=T0 + _ALERT_LAG)
        return store, alert

    def ground_truth(self) -> GroundTruth:
        return GroundTruth(
            root_cause=_ROOT_CAUSE,
            remediation_class="rollback",
            min_evidence_path=["query_metrics", "query_deploys"],
        )


BAD_DEPLOY = register(BadDeploy())
