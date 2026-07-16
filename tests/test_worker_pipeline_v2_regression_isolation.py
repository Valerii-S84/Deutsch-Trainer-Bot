from __future__ import annotations

import argparse
import math
from types import SimpleNamespace

import pytest

from scripts import worker_pipeline_v2_regression_isolation as script


def test_build_parser_preserves_steady_open_loop_defaults() -> None:
    parser = script.build_parser()

    args = parser.parse_args(["run"])
    profile = script.build_arrival_profile(args)

    assert args.arrival_mode == script.DEFAULT_ARRIVAL_MODE
    assert args.target_rps == script.DEFAULT_TARGET_RPS
    assert args.total_requests == script.DEFAULT_TOTAL_REQUESTS
    assert args.session_offset == 0
    assert args.seeded_session_count == script.DEFAULT_SESSION_COUNT
    assert profile.mode == script.DEFAULT_ARRIVAL_MODE
    assert profile.metadata(args.total_requests)["burst_window_seconds"] is None
    assert math.isclose(profile.target_offset_seconds(499), 4.99, rel_tol=0, abs_tol=1e-9)


def test_burst_arrival_compresses_full_interval_into_window() -> None:
    profile = script.ArrivalProfile(
        mode=script.ARRIVAL_MODE_BURST,
        target_rps=100,
        burst_window_seconds=1.0,
        burst_interval_seconds=5.0,
    )

    assert math.isclose(profile.target_offset_seconds(0), 0.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(profile.target_offset_seconds(499), 0.998, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(profile.target_offset_seconds(500), 5.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(profile.target_offset_seconds(999), 5.998, rel_tol=0, abs_tol=1e-9)


def test_build_parser_accepts_burst_cli_flags() -> None:
    parser = script.build_parser()

    args = parser.parse_args(
        ["run", "--arrival-mode", "burst", "--burst-window-seconds", "2", "--burst-interval-seconds", "5"]
    )
    profile = script.build_arrival_profile(args)

    assert profile.mode == script.ARRIVAL_MODE_BURST
    assert profile.burst_window_seconds == 2.0
    assert profile.burst_interval_seconds == 5.0


def test_burst_metadata_exposes_peak_arrival_fields() -> None:
    profile = script.ArrivalProfile(
        mode=script.ARRIVAL_MODE_BURST,
        target_rps=100,
        burst_window_seconds=2.0,
        burst_interval_seconds=5.0,
    )

    metadata = profile.metadata(500)

    assert metadata["scheduler"] == "open_loop"
    assert metadata["mode"] == script.ARRIVAL_MODE_BURST
    assert metadata["burst_window_seconds"] == 2.0
    assert metadata["burst_interval_seconds"] == 5.0
    assert metadata["peak_rate_multiplier"] == 2.5
    assert metadata["estimated_peak_rps"] == 250.0
    assert metadata["estimated_requests_per_full_interval"] == 500.0
    assert metadata["scheduled_dispatch_span_sec"] == 1.996


def test_build_arrival_profile_rejects_window_larger_than_interval() -> None:
    args = argparse.Namespace(
        arrival_mode=script.ARRIVAL_MODE_BURST,
        burst_interval_seconds=1.0,
        burst_window_seconds=2.0,
        target_rps=100,
        total_requests=500,
    )

    with pytest.raises(SystemExit, match="--burst-window-seconds"):
        script.build_arrival_profile(args)


class FakeQueuePool:
    def size(self) -> int:
        return 20

    def checkedout(self) -> int:
        return 3

    def checkedin(self) -> int:
        return 17

    def overflow(self) -> int:
        return 5

    def status(self) -> str:
        return "queue ok"


class FakeNullPool:
    def status(self) -> str:
        return "null ok"


def test_sample_pool_state_reads_queue_pool_metrics() -> None:
    sample = script.sample_pool_state("app", FakeQueuePool())

    assert sample["label"] == "app"
    assert sample["pool_class"] == "FakeQueuePool"
    assert sample["size"] == 20
    assert sample["checked_out"] == 3
    assert sample["checked_in"] == 17
    assert sample["overflow"] == 5
    assert sample["status"] == "queue ok"


def test_sample_pool_state_handles_null_pool_without_queue_methods() -> None:
    sample = script.sample_pool_state("app", FakeNullPool())

    assert sample["pool_class"] == "FakeNullPool"
    assert sample["size"] == 0
    assert sample["checked_out"] == 0
    assert sample["checked_in"] == 0
    assert sample["overflow"] == 0
    assert sample["status"] == "null ok"


def test_current_max_rss_mb_returns_zero_when_resource_module_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "_resource", None)

    assert script.current_max_rss_mb() == 0.0


def test_current_max_rss_mb_uses_resource_module_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resource = SimpleNamespace(
        RUSAGE_SELF=1,
        getrusage=lambda _target: SimpleNamespace(ru_maxrss=2048),
    )
    monkeypatch.setattr(script, "_resource", fake_resource)

    assert script.current_max_rss_mb() == 2.0


def test_measurement_update_id_is_unique_per_run_base() -> None:
    first_run = script.measurement_update_id(1_000_000, 42)
    second_run = script.measurement_update_id(2_000_000, 42)

    assert first_run != second_run
    assert second_run - first_run == 1_000_000


def test_measurement_session_id_applies_offset() -> None:
    assert script.measurement_session_id(0, 0) == 1
    assert script.measurement_session_id(100, 0) == 101
    assert script.measurement_session_id(100, 99) == 200


def test_build_session_selection_profile_rejects_capacity_overflow_for_unique_mode() -> None:
    args = argparse.Namespace(
        session_selection=script.DEFAULT_SESSION_SELECTION,
        total_requests=100,
        session_offset=script.DEFAULT_SESSION_COUNT,
        seeded_session_count=script.DEFAULT_SESSION_COUNT,
    )

    with pytest.raises(SystemExit, match="seeded session capacity"):
        script.build_session_selection_profile(args)


def test_hotset_session_selection_reuses_bounded_pool_and_reduces_seed_requirement() -> None:
    profile = script.SessionSelectionProfile(
        mode=script.SESSION_SELECTION_HOTSET,
        session_offset=0,
        seeded_session_count=600,
        total_requests=1_000,
        hot_session_ratio=0.5,
        hot_session_pool_size=10,
    )

    assert profile.session_id(0) == 1
    assert profile.session_id(9) == 10
    assert profile.session_id(10) == 1
    assert profile.session_id(499) == 10
    assert profile.session_id(500) == 11
    assert profile.required_seeded_sessions() == 510


def test_build_session_selection_profile_accepts_hotset_cli_values() -> None:
    args = argparse.Namespace(
        session_selection=script.SESSION_SELECTION_HOTSET,
        hot_session_ratio=0.75,
        hot_session_pool_size=25,
        total_requests=1_000,
        session_offset=100,
        seeded_session_count=400,
    )

    profile = script.build_session_selection_profile(args)

    assert profile.mode == script.SESSION_SELECTION_HOTSET
    assert profile.session_id(0) == 101
    assert profile.session_id(749) == 125
    assert profile.session_id(750) == 126


def test_resolve_max_in_flight_defaults_to_pgbouncer_effective_limit() -> None:
    args = argparse.Namespace(max_in_flight=None)
    settings = argparse.Namespace(
        db_connection_backend=argparse.Namespace(value="pgbouncer_transaction"),
        effective_bot_in_flight_limit=168,
    )

    assert script.resolve_max_in_flight(args, settings) == 168
