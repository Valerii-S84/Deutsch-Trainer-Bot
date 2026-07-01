from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class BackpressureSnapshot:
    limit: int
    in_flight: int
    available: int
    rejected_total: int
    seconds_since_last_rejection: float | None
    saturated: bool


class BackpressureMonitor:
    def __init__(self) -> None:
        self._limit = 0
        self._in_flight = 0
        self._rejected_total = 0
        self._last_rejection_at: float | None = None

    def configure(self, *, limit: int) -> None:
        self._limit = max(0, limit)

    def acquired(self) -> None:
        self._in_flight += 1

    def released(self) -> None:
        self._in_flight = max(0, self._in_flight - 1)

    def rejected(self) -> None:
        self._rejected_total += 1
        self._last_rejection_at = monotonic()

    def snapshot(self) -> BackpressureSnapshot:
        now = monotonic()
        seconds_since_last_rejection = (
            None if self._last_rejection_at is None else max(0.0, now - self._last_rejection_at)
        )
        recent_rejection = seconds_since_last_rejection is not None and seconds_since_last_rejection <= 30
        saturated = (self._limit > 0 and self._in_flight >= self._limit) or recent_rejection
        return BackpressureSnapshot(
            limit=self._limit,
            in_flight=self._in_flight,
            available=max(0, self._limit - self._in_flight),
            rejected_total=self._rejected_total,
            seconds_since_last_rejection=seconds_since_last_rejection,
            saturated=saturated,
        )


global_backpressure_monitor = BackpressureMonitor()
