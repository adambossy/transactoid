"""Observability for Penny — OpenTelemetry tracing exported to Langfuse.

The agent loop is traced by agent-harness's ``OTELSubscriber`` (Penny only
wires the OTLP exporter); the categorizer is traced with the
``categorizer_span`` / ``llm_generation`` helpers. See
:mod:`penny.observability.otel`.
"""

from __future__ import annotations

from .otel import (
    categorizer_span,
    current_trace_id,
    current_trace_url,
    flush,
    is_enabled,
    llm_generation,
    shutdown,
    start_run_trace_task,
)

__all__ = [
    "categorizer_span",
    "current_trace_id",
    "current_trace_url",
    "flush",
    "is_enabled",
    "llm_generation",
    "shutdown",
    "start_run_trace_task",
]
