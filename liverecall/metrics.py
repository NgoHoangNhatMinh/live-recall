"""Counters and observability.

OWNER D.

This module exists because the two advanced hidden challenges are graded on
behaviour that is invisible in the load-client CSV. The CSV shows what clients
received; it cannot show why. These counters show why: how often the overload
policy fired, how deep queues got, how many provisional revisions were
superseded rather than delivered.

Every number the report claims about backpressure should come from here, and
every viva question of the form "show me that your policy actually engaged"
is answered from here.

Keep this cheap. It runs on the fan-out path.
"""

from __future__ import annotations

import time
from collections import Counter


class Metrics:
    """Monotonic counters plus a few gauges and high-water marks."""

    __slots__ = ("_counters", "_gauges", "_peaks", "_started")

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, float] = {}
        self._peaks: dict[str, float] = {}
        self._started = time.monotonic()

    # --- recording ------------------------------------------------------

    def incr(self, name: str, amount: int = 1) -> None:
        """Add to a monotonic counter."""
        self._counters[name] += amount

    def gauge(self, name: str, value: float) -> None:
        """Record a current value, overwriting the previous one."""
        self._gauges[name] = value

    def peak(self, name: str, value: float) -> None:
        """Record a high-water mark, keeping the largest value ever seen."""
        if value > self._peaks.get(name, float("-inf")):
            self._peaks[name] = value

    # --- reading --------------------------------------------------------

    def get(self, name: str) -> float:
        return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, float]:
        """Flat dict of everything recorded so far, for logs or a report table."""
        out: dict[str, float] = {"uptime_s": round(time.monotonic() - self._started, 3)}
        out.update(self._counters)
        out.update(self._gauges)
        out.update({f"peak_{k}": v for k, v in self._peaks.items()})
        return out

    def log_line(self) -> str:
        """One-line form for periodic stdout logging during experiments."""
        snap = self.snapshot()
        interesting = (
            "uptime_s",
            "clients_connected",
            "updates_in",
            "updates_accepted",
            "updates_rejected_stale",
            "updates_rejected_duplicate",
            "frames_sent",
            "provisionals_coalesced",
            "provisionals_dropped",
            "overload_engaged",
            "clients_disconnected_overflow",
            "peak_queue_depth",
            "history_items",
            "history_unrecoverable_gap",
        )
        parts = [f"{k}={snap[k]:g}" for k in interesting if k in snap]
        return "metrics " + " ".join(parts)
