from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from agent.config import settings

F = TypeVar("F", bound=Callable[..., Any])

_langfuse = None
_observe = None


def _init_langfuse() -> bool:
    global _langfuse, _observe
    if _observe is not None:
        return _observe is not False

    if settings.agent_mock_mode or not settings.has_langfuse:
        _observe = False
        return False

    try:
        from langfuse import Langfuse, observe

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _observe = observe
        return True
    except Exception:
        _observe = False
        return False


def traced(name: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        if _init_langfuse() and _observe is not False:
            return _observe(name=name)(func)  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def flush_traces() -> None:
    if _langfuse is not None:
        _langfuse.flush()


def get_current_trace_id() -> str | None:
    if not _init_langfuse() or _langfuse is None:
        return None
    try:
        from langfuse import get_client

        client = get_client()
        trace_id = client.get_current_trace_id()
        return trace_id
    except Exception:
        return None


def get_trace_url(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    host = settings.langfuse_host.rstrip("/")
    return f"{host}/trace/{trace_id}"
