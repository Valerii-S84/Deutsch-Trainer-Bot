from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from time import perf_counter

_current_timing: ContextVar[dict[str, float] | None] = ContextVar("current_timing", default=None)
_current_timing_metrics: ContextVar[dict[str, float] | None] = ContextVar(
    "current_timing_metrics",
    default=None,
)
_current_query_label: ContextVar[str | None] = ContextVar("current_timing_query_label", default=None)


def begin_timing() -> tuple[
    dict[str, float],
    dict[str, float],
    tuple[Token[dict[str, float] | None], Token[dict[str, float] | None]],
]:
    timings: dict[str, float] = {}
    metrics: dict[str, float] = {}
    timing_token = _current_timing.set(timings)
    metric_token = _current_timing_metrics.set(metrics)
    return timings, metrics, (timing_token, metric_token)


def end_timing(tokens: tuple[Token[dict[str, float] | None], Token[dict[str, float] | None]]) -> None:
    timing_token, metric_token = tokens
    _current_timing.reset(timing_token)
    _current_timing_metrics.reset(metric_token)


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


def record_timing_metric(name: str, value: float | int) -> None:
    metrics = _current_timing_metrics.get()
    if metrics is None:
        return
    metrics[name] = metrics.get(name, 0.0) + float(value)


@contextmanager
def timing_query(label: str) -> Iterator[None]:
    token = _current_query_label.set(label)
    try:
        yield
    finally:
        _current_query_label.reset(token)


def current_timing_query_label() -> str | None:
    return _current_query_label.get()
