"""Shared wire types between the sandbox runner and the Fly relay.

This is the ONE package both the untrusted runner and the trusted website
import. It is deliberately tiny and dependency-light (pydantic + agent-harness
types only) so the seam stays thin.
"""

from __future__ import annotations

from .events import (
    WIRE_VERSION,
    decode_envelope,
    decode_event,
    encode_envelope,
    encode_event,
)
from .turn import ModelConfig, PersistCallback, ToolServer, TurnPayload

__all__ = [
    "WIRE_VERSION",
    "encode_event",
    "decode_event",
    "encode_envelope",
    "decode_envelope",
    "TurnPayload",
    "ModelConfig",
    "ToolServer",
    "PersistCallback",
]
