from __future__ import annotations

from app.runtime.webhook_profiling import WebhookProfileCollector


def test_webhook_profile_collector_records_dispatch_gap_spans(tmp_path) -> None:
    collector = WebhookProfileCollector(
        latency_output_path=str(tmp_path / "latency.json"),
        cpu_output_path=None,
        cpu_interval_ms=10.0,
    )

    collector.record_request(
        request_path="/telegram/webhook",
        status_code=200,
        total_ms=120.0,
        spans_ms={
            "webhook.dispatch_ms": 100.0,
            "webhook.feed_webhook_update_ms": 99.0,
            "webhook.feed_update_ms": 90.0,
            "middleware.backpressure_acquire_ms": 1.0,
            "middleware.security_duplicate_guard_ms": 2.0,
            "middleware.security_rate_limit_ms": 3.0,
            "middleware.logging_ms": 4.0,
            "handler.training_answer_total_ms": 60.0,
            "handler.training_answer_submit_ms": 50.0,
            "answer.validate_ms": 40.0,
        },
        metrics={},
    )

    summary = collector._latency_summary()
    spans = summary["span_p95_ms"]
    assert spans["derived.dispatch_minus_handler_submit_ms"] == 50.0
    assert spans["derived.handler_non_submit_ms"] == 10.0
    assert spans["derived.feed_webhook_update_minus_feed_update_ms"] == 9.0
    assert spans["derived.dispatch_unattributed_after_known_gap_ms"] == 30.0
    assert summary["p95_request_by_span"]["answer.validate_ms"]["spans_ms"]["answer.validate_ms"] == 40.0
