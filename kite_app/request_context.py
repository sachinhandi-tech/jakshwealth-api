"""Per-request values already available on the HTTP call."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[Optional[str]] = ContextVar("kite_request_id", default=None)
platform_user_var: ContextVar[Optional[str]] = ContextVar("kite_platform_user", default=None)
