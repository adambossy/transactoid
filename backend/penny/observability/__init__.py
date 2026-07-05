"""Observability for Penny.

Two orthogonal concerns live here:

* *Tracing* — OpenTelemetry spans exported to Langfuse. The agent loop is
  traced by agent-harness's ``OTELSubscriber`` (Penny only wires the OTLP
  exporter); the categorizer uses the ``categorizer_span`` / ``llm_generation``
  helpers. See :mod:`penny.observability.otel`.
* *Error tracking* — unhandled exceptions shipped to Sentry via
  :func:`init_sentry`. See :mod:`penny.observability.sentry`.
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
from .sentry import init_sentry

__all__ = [
    "categorizer_span",
    "current_trace_id",
    "current_trace_url",
    "flush",
    "init_sentry",
    "is_enabled",
    "llm_generation",
    "shutdown",
    "start_run_trace_task",
]
