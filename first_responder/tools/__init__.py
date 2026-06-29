"""The tool surface — the agent's only interface to the world.

The five tools (``query_logs``, ``query_metrics``, ``get_traces``,
``query_deploys``, ``search_runbooks``) are pure, read-only views over a
:class:`~first_responder.simulator.store.TelemetryStore`. :mod:`.base` defines the
shared contract (typed results, errors-as-values) and :mod:`.registry` provides the
single dispatch surface the agent calls through.
"""
