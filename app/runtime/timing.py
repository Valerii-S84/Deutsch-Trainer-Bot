from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter

_current_timing: ContextVar[dict[str, float] | None] = ContextVar("current_timing", default=None)


def begin_timing() -> tuple[dict[str, float], Token[dict[str, float] | None]]:
    timings: dict[str, float] = {}
    token = _current_timing.set(timings)
    return timings, token


def end_timing(token: Token[dict[str, float] | None]) -> None:
    _current_timing.reset(token)


@contextmanager
def timing_span(name: str) -> Iterator[None]:
    timings = _current_timing.get()
    if timings is None:
        yield
        return

    started = perf_counter()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0.0) + ((perf_counter() - started) * 1000)
