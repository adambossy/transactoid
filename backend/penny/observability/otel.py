"""OpenTelemetry tracing for Penny, exported to Langfuse over OTLP.

This is the vendor-neutral end-state: the agent loop is traced entirely by
agent-harness's :class:`~agent_harness.tracing.otel.OTELSubscriber` (an
EventBus subscriber that emits GenAI-semconv spans) — Penny owns no agent-loop
translation code, only the *exporter wiring*. The categorizer (which never
touches agent-harness — it calls the OpenAI/Gemini SDKs directly) is traced
here with two thin OTEL context-manager helpers.

All spans flow through one OTEL ``TracerProvider`` whose ``BatchSpanProcessor``
ships to Langfuse's OTLP endpoint. Point it at any other OTLP backend by
changing the exporter — nothing else is Langfuse-specific except the handful
of ``langfuse.*`` attribute hints we attach so the Langfuse UI renders
sessions/tags/IO nicely.

Configuration (see ``.env.example``):

* ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` — OTLP Basic-auth creds.
* ``LANGFUSE_HOST`` (or ``LANGFUSE_BASE_URL``) — instance URL; defaults to
  Langfuse Cloud.
* ``PENNY_LANGFUSE_ENABLED`` — explicit ``true``/``false`` override; default on
  iff both keys are present.
* ``PENNY_LANGFUSE_ENVIRONMENT`` — environment tag (e.g. ``development``).

Everything degrades to a strict no-op when unconfigured.
"""

from __future__ import annotations

import base64
import contextlib
from contextlib import contextmanager
import json
import os
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncio
    from collections.abc import Iterator

    from agent_harness.core.events import EventBus


# --- GenAI semantic-convention + Langfuse attribute keys ---------------------

_OP = "gen_ai.operation.name"
_REQUEST_MODEL = "gen_ai.request.model"
_USAGE_IN = "gen_ai.usage.input_tokens"
_USAGE_OUT = "gen_ai.usage.output_tokens"
_COMPLETION = "gen_ai.completion"
_PROMPT = "gen_ai.prompt"
# Langfuse-specific hints (harmless on other OTLP backends).
_LF_INPUT = "langfuse.observation.input"
_LF_OUTPUT = "langfuse.observation.output"
_LF_SESSION = "session.id"
_LF_ENV = "langfuse.environment"


# --- Configuration + provider singleton --------------------------------------

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_enabled: bool | None = None
_provider: Any = None


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def is_enabled() -> bool:
    """Whether tracing is active for this process (cached)."""
    global _enabled
    if _enabled is not None:
        return _enabled

    has_keys = bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
        and os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    flag = _env_flag("PENNY_LANGFUSE_ENABLED")
    if flag is False:
        _enabled = False
    elif flag is True and not has_keys:
        logger.warning(
            "PENNY_LANGFUSE_ENABLED=true but LANGFUSE_PUBLIC_KEY/"
            "LANGFUSE_SECRET_KEY are not set; OTEL tracing stays off."
        )
        _enabled = False
    else:
        _enabled = has_keys
    if _enabled:
        logger.info("Langfuse/OTEL tracing enabled")
    return _enabled


def _otlp_endpoint() -> str:
    host = (
        os.environ.get("LANGFUSE_HOST")
        or os.environ.get("LANGFUSE_BASE_URL")
        or "https://cloud.langfuse.com"
    ).rstrip("/")
    return f"{host}/api/public/otel/v1/traces"


def _otlp_headers() -> dict[str, str]:
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "x-langfuse-ingestion-version": "4",
    }


def _get_provider() -> Any:
    """Build (once) the TracerProvider that exports to Langfuse over OTLP."""
    global _provider
    if not is_enabled():
        return None
    if _provider is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        env = os.environ.get("PENNY_LANGFUSE_ENVIRONMENT", "").strip() or "default"
        resource = Resource.create(
            {"service.name": "penny", "deployment.environment.name": env}
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=_otlp_endpoint(), headers=_otlp_headers())
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _provider = provider
    return _provider


def _tracer(name: str) -> Any:
    provider = _get_provider()
    if provider is None:
        return None
    return provider.get_tracer(name)


def _environment() -> str:
    return os.environ.get("PENNY_LANGFUSE_ENVIRONMENT", "").strip() or "default"


def flush() -> None:
    """Flush buffered spans. No-op when disabled. Call before process exit."""
    if _provider is not None:
        with contextlib.suppress(Exception):
            _provider.force_flush()


def shutdown() -> None:
    """Flush and tear down the exporter. No-op when disabled."""
    if _provider is not None:
        with contextlib.suppress(Exception):
            _provider.shutdown()


# --- Serialization + no-op handle --------------------------------------------


def _json(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


class _NoopGeneration:
    def update(self, **_: Any) -> _NoopGeneration:
        return self


_NOOP = _NoopGeneration()


class _Generation:
    """Thin handle over a live OTEL span for an LLM call.

    Exposes the ``update(output=..., usage_details=...)`` shape the categorizer
    uses; the underlying span is ended by :func:`llm_generation` on block exit.
    """

    def __init__(self, span: Any) -> None:
        self._span = span

    def update(
        self,
        *,
        output: Any = None,
        usage_details: dict[str, int] | None = None,
        model: str | None = None,
    ) -> _Generation:
        if model:
            self._span.set_attribute(_REQUEST_MODEL, model)
        if usage_details:
            if "input" in usage_details:
                self._span.set_attribute(_USAGE_IN, usage_details["input"])
            if "output" in usage_details:
                self._span.set_attribute(_USAGE_OUT, usage_details["output"])
        if output is not None:
            text = output if isinstance(output, str) else _json(output)
            self._span.set_attribute(_COMPLETION, text)
            self._span.set_attribute(_LF_OUTPUT, text)
        return self


# --- Categorizer helpers (context-manager based) -----------------------------


@contextmanager
def categorizer_span(
    name: str,
    *,
    input: Any = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a root span for a categorizer run (the current OTEL context).

    Generations created via :func:`llm_generation` inside the ``with`` body —
    including those spawned in concurrent ``asyncio.gather`` batches — nest
    under this span (OTEL context propagates into the child tasks). No-op when
    tracing is disabled.
    """
    tracer = _tracer("penny.categorizer")
    if tracer is None:
        yield _NOOP
        return
    attributes: dict[str, Any] = {_OP: "chain", _LF_ENV: _environment()}
    if input is not None:
        attributes[_LF_INPUT] = _json(input)
    if session_id:
        attributes[_LF_SESSION] = session_id
    if metadata:
        for key, value in metadata.items():
            attributes[f"langfuse.metadata.{key}"] = _json(value)
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        yield span


@contextmanager
def llm_generation(name: str, *, model: str | None, input: Any = None) -> Iterator[Any]:
    """Open a ``generation`` span around a single provider call.

    Parents to the current span (e.g. a :func:`categorizer_span`). The caller
    sets output/usage via the yielded handle's ``update(...)``; the span ends
    on block exit.
    """
    tracer = _tracer("penny.categorizer")
    if tracer is None:
        yield _NOOP
        return
    attributes: dict[str, Any] = {_OP: "chat"}
    if model:
        attributes[_REQUEST_MODEL] = model
    if input is not None:
        text = input if isinstance(input, str) else _json(input)
        attributes[_PROMPT] = text
        attributes[_LF_INPUT] = text
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        yield _Generation(span)


# --- Agent-loop tracing (delegated to agent-harness's OTELSubscriber) ---------


def start_run_trace_task(
    bus: EventBus | None,
    *,
    source: str,
    trace_name: str = "penny-agent-run",
    session_id: str | None = None,
    user_id: str | None = None,
    prompt: str | None = None,
    tags: list[str] | None = None,
) -> asyncio.Task[None] | None:
    """Attach agent-harness's OTEL subscriber to ``bus`` and return its task.

    Returns ``None`` when tracing is disabled or ``bus`` is ``None``. Subscribe
    BEFORE the run starts publishing; await the returned task after the bus
    closes so dangling spans are ended.
    """
    tracer = _tracer("agent_harness")
    if tracer is None or bus is None:
        return None

    from agent_harness.tracing import OTELSubscriber

    root_attributes: dict[str, Any] = {
        _LF_ENV: _environment(),
        # Per-source feature tag so chat vs cron runs are filterable.
        "langfuse.trace.tags": tags if tags is not None else [source],
        "langfuse.metadata.source": source,
    }
    if session_id:
        root_attributes[_LF_SESSION] = session_id
    if user_id:
        root_attributes["user.id"] = user_id
    if prompt is not None:
        root_attributes[_LF_INPUT] = prompt

    subscriber = OTELSubscriber(
        bus, tracer, root_name=trace_name, root_attributes=root_attributes
    )
    return subscriber.start()
