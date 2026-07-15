"""Sentry error tracking for Penny.

Captures unhandled exceptions from every entrypoint — the FastAPI app
(``penny.api.main``) and the Typer CLI / cron jobs (``penny.cli``) — and ships
them to Sentry. ``sentry-sdk`` auto-enables its FastAPI/Starlette and logging
integrations when those packages are importable, so request-handler and
background-job crashes are reported without per-call-site wiring.

This is error *tracking*, orthogonal to the OTEL/Langfuse *tracing* in
:mod:`penny.observability.otel`: exceptions go to Sentry, spans go to Langfuse.

Configuration (see ``.env.example``):

* ``PENNY_SENTRY_DSN`` — the ingest endpoint. Defaults to the Penny project
  DSN below; a Sentry DSN is a *public* client identifier (it ships inside
  browser/mobile bundles), so committing the default is safe and keeps error
  reporting on by default. Set it to an empty value to disable.
* ``PENNY_SENTRY_ENABLED`` — explicit ``true``/``false`` override; default on
  iff a DSN is present.
* ``PENNY_SENTRY_ENVIRONMENT`` — environment tag. Deploy sets ``production``
  (fly ``[env]`` + the cron ``config.env``); unset means a local/dev process,
  which reports as ``development``. Never rely on the SDK default — it is
  ``production``, which made laptop dev servers page prod alerts.

:func:`init_sentry` is idempotent and degrades to a strict no-op when disabled
or unconfigured.
"""

from __future__ import annotations

import os

from loguru import logger

# A Sentry DSN is a public client key (it is embedded in shipped client apps),
# so committing the project default is safe and keeps reporting on by default.
_DEFAULT_DSN = (
    "https://a39721c83f610bd50c2bc134ff77819a"
    "@o4511683759439872.ingest.us.sentry.io/4511683766845440"
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_initialized = False


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def _dsn() -> str:
    """Resolve the DSN: unset falls back to the default; empty disables."""
    raw = os.environ.get("PENNY_SENTRY_DSN")
    return _DEFAULT_DSN if raw is None else raw.strip()


def is_enabled() -> bool:
    """Whether Sentry should initialize for this process.

    Default: on iff a DSN resolves. ``PENNY_SENTRY_ENABLED`` overrides, but can
    never enable reporting without a DSN.
    """
    has_dsn = bool(_dsn())
    override = _env_flag("PENNY_SENTRY_ENABLED")
    return has_dsn if override is None else (override and has_dsn)


def init_sentry() -> None:
    """Initialize Sentry once per process. Idempotent; no-op when disabled."""
    global _initialized
    if _initialized:
        return
    _initialized = True  # a no-op decision is still "done" — don't re-evaluate.
    if not is_enabled():
        return
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - dependency present in prod
        logger.warning("sentry-sdk not installed; error tracking disabled")
        return
    sentry_sdk.init(
        dsn=_dsn(),
        # Unset ⇒ "development": only deploy-supplied env says "production".
        # (Passing None would fall back to the SDK default — "production".)
        environment=os.environ.get("PENNY_SENTRY_ENVIRONMENT", "").strip()
        or "development",
        # Attach request headers and user IP/PII. See Sentry data-management
        # docs: https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
    )
    logger.info("Sentry error tracking initialized")
