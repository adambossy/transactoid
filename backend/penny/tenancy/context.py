from __future__ import annotations

import contextvars
from dataclasses import dataclass
import enum
import uuid

NIL_USER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class SessionMode(enum.Enum):
    INDIVIDUAL = "individual"
    JOINT = "joint"


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: uuid.UUID
    household_id: uuid.UUID
    session_mode: SessionMode = SessionMode.INDIVIDUAL


def effective_user_id(ctx: RequestContext) -> uuid.UUID:
    if ctx.session_mode is SessionMode.JOINT:
        return NIL_USER_UUID
    return ctx.user_id


_current: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "penny_request_context", default=None
)


def set_request_context(ctx: RequestContext | None) -> contextvars.Token:
    return _current.set(ctx)


def reset_request_context(token: contextvars.Token) -> None:
    _current.reset(token)


def get_request_context() -> RequestContext | None:
    return _current.get()


def require_request_context() -> RequestContext:
    ctx = _current.get()
    if ctx is None:
        raise LookupError("No RequestContext set for this execution context")
    return ctx
