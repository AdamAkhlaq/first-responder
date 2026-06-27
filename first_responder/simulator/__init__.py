"""The ground-truth engine: scenarios, the fault→telemetry renderer, and the store.

Nothing here is visible to the agent. The simulator writes telemetry into a
:class:`~first_responder.simulator.store.TelemetryStore`; the tools layer reads it
back. That write/read split is the seam that keeps reads pure and replayable.
"""
