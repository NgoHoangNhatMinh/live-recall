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
    """Counters, current-value gauges, and recorded peaks.

    Intended for synchronous calls within the server's event loop.
    Counter increments should be non-negative for cumulative measurements.
    
    """

    __slots__ = ("_counters", "_gauges", "_peaks", "_started")

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, float] = {}
        self._peaks: dict[str, float] = {}
        self._started = time.monotonic()

    # --- recording ------------------------------------------------------

    def incr(self, name: str, amount: int = 1) -> None:
        """Add to a counter, creating it when first used.

        Existing behavior is preserved: this method does not reject
        negative increments. Use non-negative amounts for cumulative
        counters and gauge() for current values.
        """
        self._counters[name] += amount

    def gauge(self, name: str, value: float) -> None:
        """Set the current value, replacing its previous measurement."""
        self._gauges[name] = value

    def peak(self, name: str, value: float) -> None:
        """Keep the largest value recorded for this measurement.

        Example:
            peak("queue_depth", 12)

        The snapshot exposes this as "peak_queue_depth".
        """
        if value > self._peaks.get(name, float("-inf")):
            self._peaks[name] = value

    # --- reading --------------------------------------------------------

    def get(self, name: str) -> float:
        """Return a counter value, or zero if it has not been recorded.

        This reads counters only. Use snapshot() for gauges and peaks.
        """
        return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, float]:
        """Return a new flat dictionary of recorded measurements.

        Unknown or unrecorded measurements are omitted.
        Taking a snapshot does not reset any measurements.
        """
        out: dict[str, float] = {
            "uptime_s": round(time.monotonic() - self._started, 3)
        }

        out.update(self._counters)
        out.update(self._gauges)
        out.update({
            f"peak_{name}": value
            for name, value in self._peaks.items()
        })

        return out

    def log_line(self) -> str:
        """Format selected measurements as one line.

        The application must call and print this method's result.
        Missing measurements are omitted, not reported as zero.
        """
        snap = self.snapshot()

        interesting = (
            # Runtime and connected clients.
            "uptime_s",
            "clients_connected",

            # Source connection and input validation.
            "source_connects",
            "source_invalid_hello",
            "updates_in",
            "source_bad_json",
            "source_invalid_update",
            "source_unknown_type",
            "source_done",

            # Caption-state decisions.
            "updates_accepted",
            "updates_rejected_stale",
            "updates_rejected_duplicate",

            # Delivery and overload handling.
            "frames_sent",
            "provisionals_coalesced",
            "provisionals_dropped",
            "overload_engaged",
            "clients_disconnected_overflow",
            "peak_queue_depth",

            # Recovery history.
            "history_items",
            "history_unrecoverable_gap",
        )

        parts = [
            f"{name}={snap[name]:g}"
            for name in interesting
            if name in snap
        ]

        return "metrics " + " ".join(parts)
