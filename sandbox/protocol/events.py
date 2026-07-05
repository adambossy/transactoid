"""Versioned JSON codec for the agent-harness ``Event`` union.

Harness events are frozen ``@dataclass`` instances with pydantic payloads
(``Message``, ``Usage``, ``Cost``, content blocks) and no built-in JSON
round-trip. This module is the one wire artifact the runner and the Fly relay
share: the runner ``encode``s each bus event into a self-describing envelope,
the relay ``decode``s it back into a real harness ``Event`` so the existing
``penny.api.bridge._translate`` sees exactly the objects it does today.

Two members need special handling (both documented on the plan's Event-stream
page):

* ``RunEnd.result`` is a Layer-3 ``RunResult`` that never rode the bus to the
  UI — it is dropped to ``None`` on the wire; the relay rebuilds persisted
  parts from the streamed events, never from ``result``.
* ``Error.cause`` is an exception *type*, serialized by qualified name.

Everything else round-trips by value.
"""

from __future__ import annotations

import dataclasses
import importlib
from typing import Any

import agent_harness.core.events as _ev
import agent_harness.core.models as _models
from agent_harness.core.tools import ToolResult
from pydantic import BaseModel

WIRE_VERSION = 1

# --- Registries --------------------------------------------------------------

# Every event dataclass defined in the harness events module (public names only;
# the module's private ``_Subscriber`` helper is a dataclass too).
_EVENT_BY_NAME: dict[str, type] = {
    name: obj
    for name, obj in vars(_ev).items()
    if isinstance(obj, type)
    and dataclasses.is_dataclass(obj)
    and getattr(obj, "__module__", "") == _ev.__name__
    and not name.startswith("_")
}

# Fields dropped from the wire (see module docstring), keyed by event name.
_DROP_FIELDS: dict[str, set[str]] = {"RunEnd": {"result"}}


def _qual(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _build_pyd_registry() -> dict[str, type[BaseModel]]:
    reg: dict[str, type[BaseModel]] = {}
    for name in (
        "Message",
        "Usage",
        "Cost",
        "TextBlock",
        "ToolCallBlock",
        "ToolResultBlock",
        "ImageBlock",
        "ThinkingBlock",
    ):
        cls = getattr(_models, name, None)
        if cls is not None:
            reg[_qual(cls)] = cls
    # ApprovalRequest rides ApprovalRequested.requests.
    try:
        from agent_harness.core.run_state import ApprovalRequest

        reg[_qual(ApprovalRequest)] = ApprovalRequest
    except Exception:  # pragma: no cover - optional
        pass
    return reg


_PYD_BY_QUAL: dict[str, type[BaseModel]] = _build_pyd_registry()


# --- Value (de)serialization -------------------------------------------------


def _encode_value(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, BaseModel):
        return {"__pyd__": _qual(type(v)), "d": v.model_dump(mode="json")}
    if isinstance(v, ToolResult):
        return {
            "__tr__": {
                "content": [_encode_value(b) for b in v.content],
                "error": v.error,
                "metadata": v.metadata,
                "structured_content": v.structured_content,
            }
        }
    if isinstance(v, type) and issubclass(v, BaseException):
        return {"__type__": {"m": v.__module__, "q": v.__qualname__}}
    if isinstance(v, (list, tuple)):
        return [_encode_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _encode_value(x) for k, x in v.items()}
    # Fallback: best-effort string so an exotic value never kills the wire.
    return str(v)


def _resolve_type(module: str, qual: str) -> type:
    obj: Any = importlib.import_module(module)
    for part in qual.split("."):
        obj = getattr(obj, part)
    return obj


def _decode_value(v: Any) -> Any:
    if isinstance(v, list):
        return [_decode_value(x) for x in v]
    if isinstance(v, dict):
        if "__pyd__" in v:
            cls = _PYD_BY_QUAL[v["__pyd__"]]
            return cls.model_validate(v["d"])
        if "__tr__" in v:
            tr = v["__tr__"]
            return ToolResult(
                content=[_decode_value(b) for b in tr["content"]],
                error=tr["error"],
                metadata=tr["metadata"],
                structured_content=tr["structured_content"],
            )
        if "__type__" in v:
            t = v["__type__"]
            return _resolve_type(t["m"], t["q"])
        return {k: _decode_value(x) for k, x in v.items()}
    return v


# --- Event (de)serialization -------------------------------------------------


def encode_event(event: Any) -> dict[str, Any]:
    """Serialize one harness ``Event`` to a JSON-safe ``{"t", "d"}`` dict."""
    name = type(event).__name__
    if name not in _EVENT_BY_NAME:
        raise ValueError(f"not a known harness event: {name}")
    drop = _DROP_FIELDS.get(name, frozenset())
    data: dict[str, Any] = {}
    for f in dataclasses.fields(event):
        data[f.name] = None if f.name in drop else _encode_value(getattr(event, f.name))
    return {"t": name, "d": data}


def decode_event(obj: dict[str, Any]) -> Any:
    """Reconstruct the harness ``Event`` from :func:`encode_event`'s output."""
    name = obj["t"]
    cls = _EVENT_BY_NAME.get(name)
    if cls is None:
        raise ValueError(f"unknown event type on wire: {name}")
    kwargs = {k: _decode_value(v) for k, v in obj["d"].items()}
    return cls(**kwargs)


def encode_envelope(seq: int, event: Any) -> dict[str, Any]:
    """Wrap an event in the sequenced wire envelope the runner's log emits."""
    return {"v": WIRE_VERSION, "seq": seq, "event": encode_event(event)}


def decode_envelope(obj: dict[str, Any]) -> tuple[int, Any]:
    """Return ``(seq, event)`` from a wire envelope."""
    return obj["seq"], decode_event(obj["event"])
