from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from collections import Counter, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

_current_webhook_timings: ContextVar[dict[str, float] | None] = ContextVar(
    "current_webhook_timings",
    default=None,
)
_current_webhook_metrics: ContextVar[dict[str, float] | None] = ContextVar(
    "current_webhook_metrics",
    default=None,
)
_current_webhook_operation_label: ContextVar[str | None] = ContextVar(
    "current_webhook_operation_label",
    default=None,
)
_aiogram_profiling_installed = False
P95_SAMPLE_SPANS = (
    "webhook.dispatch_ms",
    "handler.training_answer_submit_ms",
    "answer.validate_ms",
    "middleware.security_duplicate_guard_ms",
)


def begin_webhook_timing() -> tuple[
    dict[str, float],
    dict[str, float],
    tuple[Token[dict[str, float] | None], Token[dict[str, float] | None]],
]:
    timings: dict[str, float] = {}
    metrics: dict[str, float] = {}
    timing_token = _current_webhook_timings.set(timings)
    metric_token = _current_webhook_metrics.set(metrics)
    return timings, metrics, (timing_token, metric_token)


def end_webhook_timing(
    tokens: tuple[Token[dict[str, float] | None], Token[dict[str, float] | None]]
) -> None:
    timing_token, metric_token = tokens
    _current_webhook_timings.reset(timing_token)
    _current_webhook_metrics.reset(metric_token)


def merge_webhook_timings(spans_ms: dict[str, float]) -> None:
    timings = _current_webhook_timings.get()
    if timings is None:
        return
    for name, value in spans_ms.items():
        timings[name] = timings.get(name, 0.0) + value


def merge_webhook_metrics(metrics: dict[str, float]) -> None:
    current_metrics = _current_webhook_metrics.get()
    if current_metrics is None:
        return
    for name, value in metrics.items():
        current_metrics[name] = current_metrics.get(name, 0.0) + value


@contextmanager
def webhook_timing_span(name: str) -> Iterator[None]:
    timings = _current_webhook_timings.get()
    if timings is None:
        yield
        return

    started = perf_counter()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0.0) + ((perf_counter() - started) * 1000)


def record_webhook_metric(name: str, value: float | int) -> None:
    metrics = _current_webhook_metrics.get()
    if metrics is None:
        return
    metrics[name] = metrics.get(name, 0.0) + float(value)


@contextmanager
def webhook_operation_label(label: str) -> Iterator[None]:
    token = _current_webhook_operation_label.set(label)
    try:
        yield
    finally:
        _current_webhook_operation_label.reset(token)


def current_webhook_operation_label() -> str | None:
    return _current_webhook_operation_label.get()


class CpuStackSampler:
    def __init__(self, *, interval_ms: float) -> None:
        self._interval_seconds = max(interval_ms, 1.0) / 1000.0
        self._main_thread_id = threading.main_thread().ident
        self._leaf_counts: Counter[str] = Counter()
        self._stack_counts: Counter[str] = Counter()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="webhook-cpu-stack-sampler", daemon=True)
        self._samples = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict[str, object]:
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        return {
            "sampler": "main_thread_stack_sampling",
            "sample_interval_ms": round(self._interval_seconds * 1000.0, 3),
            "sample_count": self._samples,
            "top_leaf_frames": self._top_counts(self._leaf_counts),
            "top_stacks": self._top_counts(self._stack_counts),
        }

    def _run(self) -> None:
        if self._main_thread_id is None:
            return
        while not self._stop_event.is_set():
            frame = sys._current_frames().get(self._main_thread_id)
            if frame is not None:
                stack = traceback.extract_stack(frame)
                if stack:
                    self._leaf_counts[self._frame_label(stack[-1])] += 1
                    self._stack_counts[self._stack_label(stack)] += 1
                    self._samples += 1
            time.sleep(self._interval_seconds)

    def _top_counts(self, counts: Counter[str]) -> list[dict[str, object]]:
        total = max(self._samples, 1)
        return [
            {
                "label": label,
                "samples": count,
                "share": round(count / total, 4),
            }
            for label, count in counts.most_common(20)
        ]

    @staticmethod
    def _frame_label(frame_summary: traceback.FrameSummary) -> str:
        return f"{Path(frame_summary.filename).name}:{frame_summary.name}:{frame_summary.lineno}"

    @classmethod
    def _stack_label(cls, stack: list[traceback.FrameSummary]) -> str:
        return " | ".join(cls._frame_label(frame) for frame in stack[-8:])


class WebhookProfileCollector:
    def __init__(
        self,
        *,
        latency_output_path: str | None,
        cpu_output_path: str | None,
        cpu_interval_ms: float,
    ) -> None:
        self._latency_output_path = latency_output_path
        self._cpu_output_path = cpu_output_path
        self._cpu_sampler = (
            CpuStackSampler(interval_ms=cpu_interval_ms)
            if cpu_output_path
            else None
        )
        self._requests: list[dict[str, object]] = []
        self._started = False

    @property
    def enabled(self) -> bool:
        return bool(self._latency_output_path or self._cpu_output_path)

    def start(self) -> None:
        if not self.enabled or self._started:
            return
        if self._cpu_sampler is not None:
            self._cpu_sampler.start()
        self._started = True

    def record_request(
        self,
        *,
        request_path: str,
        status_code: int,
        total_ms: float,
        spans_ms: dict[str, float],
        metrics: dict[str, float],
    ) -> None:
        if not self.enabled:
            return
        spans_with_derived = _derive_webhook_spans(spans_ms)
        self._requests.append(
            {
                "path": request_path,
                "status_code": status_code,
                "total_ms": round(total_ms, 3),
                "spans_ms": {key: round(value, 3) for key, value in sorted(spans_with_derived.items())},
                "metrics": {key: round(value, 3) for key, value in sorted(metrics.items())},
            }
        )

    def close(self) -> None:
        if not self.enabled:
            return
        if self._cpu_output_path:
            cpu_summary = {}
            if self._cpu_sampler is not None and self._started:
                cpu_summary = self._cpu_sampler.stop()
            _write_json(self._cpu_output_path, cpu_summary)
        if self._latency_output_path:
            _write_json(self._latency_output_path, self._latency_summary())

    def _latency_summary(self) -> dict[str, object]:
        total_values = [float(item["total_ms"]) for item in self._requests]
        span_values: dict[str, list[float]] = defaultdict(list)
        metric_values: dict[str, list[float]] = defaultdict(list)
        status_counts: Counter[str] = Counter()
        for item in self._requests:
            status_counts[str(item["status_code"])] += 1
            for name, value in dict(item["spans_ms"]).items():
                span_values[name].append(float(value))
            for name, value in dict(item["metrics"]).items():
                metric_values[name].append(float(value))

        return {
            "request_count": len(self._requests),
            "status_counts": dict(status_counts),
            "total_ms": _summarize_numeric(total_values),
            "span_p50_ms": {name: _percentile(values, 0.50) for name, values in sorted(span_values.items())},
            "span_p95_ms": {name: _percentile(values, 0.95) for name, values in sorted(span_values.items())},
            "span_avg_ms": {
                name: round(sum(values) / len(values), 3)
                for name, values in sorted(span_values.items())
                if values
            },
            "metric_p50": {name: _percentile(values, 0.50) for name, values in sorted(metric_values.items())},
            "metric_p95": {name: _percentile(values, 0.95) for name, values in sorted(metric_values.items())},
            "metric_avg": {
                name: round(sum(values) / len(values), 3)
                for name, values in sorted(metric_values.items())
                if values
            },
            "p95_request_by_span": {
                name: _request_at_span_percentile(self._requests, name, 0.95)
                for name in P95_SAMPLE_SPANS
            },
            "slowest_requests": sorted(self._requests, key=lambda item: float(item["total_ms"]), reverse=True)[:20],
        }


def create_webhook_profile_collector_from_env() -> WebhookProfileCollector:
    return WebhookProfileCollector(
        latency_output_path=os.environ.get("WEBHOOK_PROFILE_OUTPUT"),
        cpu_output_path=os.environ.get("WEBHOOK_CPU_PROFILE_OUTPUT"),
        cpu_interval_ms=float(os.environ.get("WEBHOOK_CPU_PROFILE_INTERVAL_MS", "10.0")),
    )


def install_aiogram_webhook_profiling() -> None:
    global _aiogram_profiling_installed
    if _aiogram_profiling_installed:
        return

    from aiogram.dispatcher.dispatcher import Dispatcher
    from aiogram.dispatcher.event.telegram import TelegramEventObserver
    from aiogram.dispatcher.router import Router
    from aiogram.types import Update

    original_model_validate = Update.model_validate
    original_feed_webhook_update = Dispatcher.feed_webhook_update
    original_feed_update = Dispatcher.feed_update
    original_router_propagate_event = Router.propagate_event
    original_observer_trigger = TelegramEventObserver.trigger

    def timed_model_validate(obj: Any, *args: Any, **kwargs: Any) -> Any:
        with webhook_timing_span("webhook.update_model_validate_ms"):
            return original_model_validate(obj, *args, **kwargs)

    async def timed_feed_webhook_update(self, *args: Any, **kwargs: Any) -> Any:
        with webhook_timing_span("webhook.feed_webhook_update_ms"):
            return await original_feed_webhook_update(self, *args, **kwargs)

    async def timed_feed_update(self, *args: Any, **kwargs: Any) -> Any:
        with webhook_timing_span("webhook.feed_update_ms"):
            return await original_feed_update(self, *args, **kwargs)

    async def timed_router_propagate_event(self, *args: Any, **kwargs: Any) -> Any:
        with webhook_timing_span("aiogram.router_propagate_event_ms"):
            return await original_router_propagate_event(self, *args, **kwargs)

    async def timed_observer_trigger(self, *args: Any, **kwargs: Any) -> Any:
        with webhook_timing_span("aiogram.observer_trigger_ms"):
            return await original_observer_trigger(self, *args, **kwargs)

    Update.model_validate = timed_model_validate  # type: ignore[assignment]
    Dispatcher.feed_webhook_update = timed_feed_webhook_update  # type: ignore[assignment]
    Dispatcher.feed_update = timed_feed_update  # type: ignore[assignment]
    Router.propagate_event = timed_router_propagate_event  # type: ignore[assignment]
    TelegramEventObserver.trigger = timed_observer_trigger  # type: ignore[assignment]
    _aiogram_profiling_installed = True


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return round(ordered[index], 3)


def _summarize_numeric(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
    return {
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def _derive_webhook_spans(spans_ms: dict[str, float]) -> dict[str, float]:
    spans = dict(spans_ms)
    _record_span_delta(
        spans,
        "derived.dispatch_minus_handler_total_ms",
        "webhook.dispatch_ms",
        "handler.training_answer_total_ms",
    )
    _record_span_delta(
        spans,
        "derived.dispatch_minus_handler_submit_ms",
        "webhook.dispatch_ms",
        "handler.training_answer_submit_ms",
    )
    _record_span_delta(
        spans,
        "derived.feed_update_minus_handler_total_ms",
        "webhook.feed_update_ms",
        "handler.training_answer_total_ms",
    )
    _record_span_delta(
        spans,
        "derived.feed_webhook_update_minus_feed_update_ms",
        "webhook.feed_webhook_update_ms",
        "webhook.feed_update_ms",
    )
    _record_span_delta(
        spans,
        "derived.handler_non_submit_ms",
        "handler.training_answer_total_ms",
        "handler.training_answer_submit_ms",
    )
    known_gap = _known_dispatch_gap_ms(spans)
    if known_gap is not None and "webhook.dispatch_ms" in spans:
        spans["derived.dispatch_unattributed_after_known_gap_ms"] = max(0.0, spans["webhook.dispatch_ms"] - known_gap)
    return spans


def _record_span_delta(spans: dict[str, float], name: str, total_name: str, child_name: str) -> None:
    if total_name in spans and child_name in spans:
        spans[name] = max(0.0, spans[total_name] - spans[child_name])


def _known_dispatch_gap_ms(spans: dict[str, float]) -> float | None:
    names = (
        "handler.training_answer_total_ms",
        "middleware.backpressure_acquire_ms",
        "middleware.backpressure_release_ms",
        "middleware.security_duplicate_guard_ms",
        "middleware.security_rate_limit_ms",
        "middleware.logging_ms",
    )
    values = [spans[name] for name in names if name in spans]
    if not values:
        return None
    return sum(values)


def _request_at_span_percentile(requests: list[dict[str, object]], span_name: str, p: float) -> dict[str, object] | None:
    matching = [request for request in requests if span_name in dict(request["spans_ms"])]
    if not matching:
        return None
    ordered = sorted(matching, key=lambda item: float(dict(item["spans_ms"])[span_name]))
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def _write_json(path: str, payload: dict[str, object]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
