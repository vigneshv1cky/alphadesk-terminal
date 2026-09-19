"""Which reader a call chain runs for (2026-09-17).

Every keyed surface in AlphaDesk answers on the READER'S own vendor keys, so
almost everything needs to know who is asking: the data router resolves their
vendors from it, the news window is owned by it, and the agent tool gate sets
it from the token a call carries.

It lives in a context variable. A sync endpoint's threadpool inherits it;
a bare background thread does NOT, which is deliberate — the ingest loops run
with no identity and may touch only public sources and each reader's own feed
(the per-reader data rule). Work a request starts and does not wait for must
carry the identity across itself.

This was `ai/llm.py`'s until the in-app model was removed (2026-09-17); it is
identity, not AI, so it stayed behind when that module went.
"""

from __future__ import annotations

import contextvars

_request_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "alphadesk_request_user", default=None)


def set_request_user(user_id: str | None) -> contextvars.Token:
    return _request_user.set(user_id)


def reset_request_user(token: contextvars.Token) -> None:
    _request_user.reset(token)


def request_user() -> str | None:
    """The signed-in reader this call chain runs for, or None outside a
    request."""
    return _request_user.get()
