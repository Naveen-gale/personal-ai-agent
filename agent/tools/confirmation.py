"""One-shot authorization context for CLI-confirmed tool execution."""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator


_authorized_tool: ContextVar[str | None] = ContextVar(
    "authorized_confirmation_tool", default=None
)


@contextmanager
def authorize_tool_call(tool_name: str) -> Iterator[None]:
    token = _authorized_tool.set(tool_name)
    try:
        yield
    finally:
        _authorized_tool.reset(token)


def consume_tool_authorization(tool_name: str) -> bool:
    if _authorized_tool.get() != tool_name:
        return False
    _authorized_tool.set(None)
    return True
