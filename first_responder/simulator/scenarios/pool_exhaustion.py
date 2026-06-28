"""The ``pool_exhaustion`` scenario: intermittent failures from a pool saturating under load.

Reasoning mode: **temporal correlation of two time series**. The cause is not a
single event (``bad_deploy``) or a structural edge (``cascading_timeout``) but the
*lockstep* of two metrics over time. Load on the affected service rises and falls
in bursts; at each load peak its connection pool pins against its ceiling
(saturates) and requests fail while waiting for a free connection; between peaks
the system recovers. So the failures are *intermittent* and *clustered* at the load
peaks, and the agent diagnoses by reading two shapes together: failures (logs) line
up with pool saturation (a metric) which lines up with the load peaks (another
metric). That cross-metric correlation is exactly
``min_evidence_path = [query_logs, query_metrics]``.

The planted red herring is a **recent, unrelated deploy** on the alerting service —
the kind of thing that tempts a reflexive "the last deploy broke it, roll it back".
It is ruled out by the same correlation: a deploy regression fails *continuously*
from the deploy onward, but here the deploy lands in a calm period with no failures
and the failures instead track the load peaks that follow. Failures coincide with
saturation, not with the deploy — and that is inferable from the metrics' shapes
alone. No agent-visible string states the cause (the eval-validity gate enforced by
``assert_no_verbatim_leak``).
"""

from __future__ import annotations

import random

from first_responder.schema.alert import Alert
from first_responder.schema.ground_truth import GroundTruth
from first_responder.schema.telemetry import DeployEvent, MetricSeries
from first_responder.schema.time import Seconds, TimeRange
from first_responder.simulator.render import render_log_stream, render_metric_series, seeded_rng
from first_responder.simulator.scenario import Scenario, register
from first_responder.simulator.store import TelemetryStore

# Incident origin and the single service in play.
T0: Seconds = 0
AFFECTED_SERVICE = "checkout-api"
DEPLOY_VERSION = "v3.1.0"

# The two correlated series the agent reads together.
LOAD_METRIC = "requests_per_second"
POOL_METRIC = "db_pool_utilization"

# Shape of the incident.
_WINDOW: Seconds = 600  # the calm pre-incident window; the incident spans the same length.
_BUCKET: Seconds = 150  # incident sub-window width; len(_LOAD_PROFILE) buckets tile _WINDOW.
_ALERT_LAG: Seconds = 40  # the alert fires this long into the first load peak.
_DEPLOY_LAG: Seconds = 200  # the red-herring deploy lands this long before T0 — recent but calm.
_PRE_WINDOW = TimeRange(start=T0 - _WINDOW, end=T0)

# Load across the consecutive incident buckets, relative to baseline. A bucket is a
# traffic PEAK when its load reaches _PEAK_LOAD: the pool saturates and requests fail
# there, and recovers in the quiet buckets between. The alternating shape is what
# makes the failures intermittent and load-correlated rather than a single onset.
_LOAD_PROFILE: tuple[float, ...] = (4.5, 1.2, 5.0, 1.1)  # PEAK, quiet, PEAK, quiet
_PEAK_LOAD = 2.0

_LOAD_BASELINE = 200.0  # requests/s at rest.
_POOL_BASELINE = 40.0  # percent utilisation at rest — well clear of the ceiling.
_POOL_SATURATION = 98.0  # percent — where utilisation pins against its ~100% ceiling at a peak.
_LOG_COUNT = 6  # healthy logs across the calm pre-window.
_ERRORS_PER_PEAK = 5  # failure logs clustered into each load-peak bucket.

# Agent-visible text. The failure log names the symptom shape (a connection could not
# be acquired in time) but never the cause: whether that contention is load-driven
# pool exhaustion or, say, a leak from the recent deploy is only decidable from the
# metric correlation — so the log cannot shortcut past query_metrics.
_ERROR_LOG_MESSAGE = "request failed: timed out acquiring a connection"
_DEPLOY_SUMMARY = f"{AFFECTED_SERVICE} {DEPLOY_VERSION}: refresh JSON log format, bump client libs"
_ALERT_SYMPTOM = f"intermittent 5xx errors and failed requests on {AFFECTED_SERVICE}"

# The hidden answer key — never present verbatim in any signal above.
_ROOT_CAUSE = (
    f"the {AFFECTED_SERVICE} connection pool saturated at peak load and requests failed "
    f"while waiting for a free connection"
)


class PoolExhaustion(Scenario):
    """A connection pool that saturates at load peaks — diagnosed by temporal correlation."""

    @property
    def name(self) -> str:
        return "pool_exhaustion"

    def activate(self, seed: int) -> tuple[TelemetryStore, Alert]:
        rng = seeded_rng(seed)
        store = TelemetryStore()

        # Calm baseline before the incident: steady low load, the pool well clear of
        # its ceiling, only healthy logs. The red-herring deploy lands in here.
        store.add_metric_series(self._render_load_and_pool(rng, _PRE_WINDOW, load_multiplier=1.0))
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

        # Red herring: a recent deploy on the alerting service that tempts a rollback.
        # It predates the failures and lands in the calm window, so it does not
        # correlate with the symptom — the metric shapes rule it out.
        store.add_deploys(
            [
                DeployEvent(
                    timestamp=T0 - _DEPLOY_LAG,
                    service=AFFECTED_SERVICE,
                    version=DEPLOY_VERSION,
                    summary=_DEPLOY_SUMMARY,
                )
            ]
        )

        # The incident: consecutive buckets whose load rises and falls. At each load
        # peak the pool saturates and requests fail; between peaks it recovers. The
        # failures track the peaks, not the deploy — that is the signal.
        for index, load_multiplier in enumerate(_LOAD_PROFILE):
            window = TimeRange.since(T0 + index * _BUCKET, _BUCKET)
            store.add_metric_series(self._render_load_and_pool(rng, window, load_multiplier))
            if load_multiplier >= _PEAK_LOAD:
                store.add_logs(
                    render_log_stream(
                        rng,
                        service=AFFECTED_SERVICE,
                        window=window,
                        count=_ERRORS_PER_PEAK,
                        level="error",
                        message=_ERROR_LOG_MESSAGE,
                    )
                )

        alert = Alert(service=AFFECTED_SERVICE, symptom=_ALERT_SYMPTOM, fired_at=T0 + _ALERT_LAG)
        return store, alert

    @staticmethod
    def _render_load_and_pool(
        rng: random.Random, window: TimeRange, load_multiplier: float
    ) -> list[MetricSeries]:
        """Render the load and pool-utilisation series for ``window`` as a correlated pair.

        The pool saturates (its tail pins near the ceiling, far above the
        ``_POOL_BASELINE`` it normally sits at) exactly when load reaches a peak, and
        otherwise sits flat at baseline. Driving both off the same ``load_multiplier``
        is what guarantees the two series move in lockstep — the temporal correlation
        the agent reads. ``tail_ratio=1.0`` keeps the saturated tail flat against the
        ceiling rather than overshooting 100%.
        """
        return [
            render_metric_series(
                rng,
                service=AFFECTED_SERVICE,
                metric=LOAD_METRIC,
                unit="req/s",
                baseline=_LOAD_BASELINE,
                anomaly_window=window,
                spike=load_multiplier,
            ),
            render_metric_series(
                rng,
                service=AFFECTED_SERVICE,
                metric=POOL_METRIC,
                unit="percent",
                baseline=_POOL_BASELINE,
                anomaly_window=window,
                spike=_POOL_SATURATION / _POOL_BASELINE if load_multiplier >= _PEAK_LOAD else 1.0,
                tail_ratio=1.0,
                jitter_fraction=0.02,
            ),
        ]

    def ground_truth(self) -> GroundTruth:
        # remediation_class="config_change": the pool's max size is a configuration
        # limit set too low for peak demand — the connections exist, the cap is just
        # too tight, so raising the pool size resolves it with no new infrastructure.
        # It is not "scale": adding app instances would not lift the pool ceiling (and
        # could worsen contention on the shared DB). It is not "rollback": the recent
        # deploy is the red herring, not the cause. (Contrast cascading_timeout, where
        # the downstream was genuinely capacity-bound and the fix was to scale.)
        return GroundTruth(
            root_cause=_ROOT_CAUSE,
            remediation_class="config_change",
            min_evidence_path=["query_logs", "query_metrics"],
        )


POOL_EXHAUSTION = register(PoolExhaustion())
