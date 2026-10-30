"""Owner A - bounded history window and HISTORY/resume semantics.

Run from the repository root:

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import unittest

from liverecall.history import HistoryWindow
from liverecall.metrics import Metrics
from liverecall.model import CaptionUpdate


class FakeClock:
    """Controllable clock, so window expiry is tested without sleeping."""

    def __init__(self, now=10_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def final(segment, revision=3, *, ts, text="done"):
    return CaptionUpdate.create(
        session="L1",
        segment=segment,
        revision=revision,
        final=True,
        source_ts=ts,
        text=text,
    )


def provisional(segment, revision=1, *, ts):
    return CaptionUpdate.create(
        session="L1",
        segment=segment,
        revision=revision,
        final=False,
        source_ts=ts,
        text="partial",
    )


def window(clock, *, window_seconds=90.0, max_items=1500, metrics=None):
    return HistoryWindow(
        window_seconds=window_seconds,
        max_items=max_items,
        metrics=metrics or Metrics(),
        clock=clock,
    )


def fill(win, clock, segments, *, step=1.0):
    """Record one final per segment, one `step` apart, advancing the clock."""
    for segment in segments:
        win.record_final(final(segment, ts=clock.now))
        clock.advance(step)


class WritePath(unittest.TestCase):
    def test_rejects_non_final(self):
        """Non-final items in HISTORY are flagged invalid by the load client."""
        clock = FakeClock()
        win = window(clock)
        with self.assertRaises(ValueError):
            win.record_final(provisional(1, ts=clock.now))

    def test_rejects_nonsense_bound(self):
        with self.assertRaises(ValueError):
            window(FakeClock(), max_items=0)


class WatermarkFiltering(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.win = window(self.clock)
        fill(self.win, self.clock, range(1, 6))  # segments 1-5, revision 3

    def test_late_join_gets_the_whole_window(self):
        items = self.win.items_since(0, 0, 60)
        self.assertEqual([u.segment for u in items], [1, 2, 3, 4, 5])

    def test_exact_watermark_match_is_excluded(self):
        """A client reporting (3, 3) already holds it - resending is a duplicate."""
        items = self.win.items_since(3, 3, 60)
        self.assertEqual([u.segment for u in items], [4, 5])

    def test_watermark_segment_with_older_revision_is_included(self):
        """Held segment 3 only up to revision 2, so revision 3 is still missing."""
        items = self.win.items_since(3, 2, 60)
        self.assertEqual([u.segment for u in items], [3, 4, 5])

    def test_watermark_at_the_head_returns_nothing(self):
        self.assertEqual(self.win.items_since(5, 3, 60), [])

    def test_watermark_beyond_the_window_returns_nothing(self):
        self.assertEqual(self.win.items_since(99, 1, 60), [])

    def test_ordering_is_oldest_to_newest(self):
        segments = [u.segment for u in self.win.items_since(0, 0, 60)]
        self.assertEqual(segments, sorted(segments))

    def test_zero_history_seconds_returns_nothing(self):
        self.assertEqual(self.win.items_since(0, 0, 0), [])
        self.assertEqual(self.win.items_since(0, 0, -5), [])


class TimeFiltering(unittest.TestCase):
    def test_history_seconds_limits_how_far_back(self):
        clock = FakeClock()
        win = window(clock)
        fill(win, clock, range(1, 11))  # one second apart, 10 segments
        # Clock is now 10 s past the first item. Ask for the last 5 s only.
        items = win.items_since(0, 0, 5)
        self.assertEqual([u.segment for u in items], [6, 7, 8, 9, 10])

    def test_a_60_second_request_is_satisfiable(self):
        """The window must be big enough for the maximum legal recall request."""
        clock = FakeClock()
        win = window(clock, window_seconds=90.0)
        fill(win, clock, range(1, 61))  # 60 segments, 60 seconds
        self.assertEqual(len(win.items_since(0, 0, 60)), 60)


class Boundedness(unittest.TestCase):
    def test_time_bound_drops_old_entries(self):
        clock = FakeClock()
        win = window(clock, window_seconds=10.0)
        fill(win, clock, range(1, 21))  # 20 s of items, 10 s window
        self.assertLessEqual(len(win), 11)
        self.assertGreaterEqual(win.oldest_segment, 10)

    def test_count_bound_holds_regardless_of_the_clock(self):
        """A bursty source must not inflate the window inside one time slice."""
        clock = FakeClock()
        win = window(clock, window_seconds=90.0, max_items=5)
        fill(win, clock, range(1, 51), step=0.0)  # 50 finals, same instant
        self.assertEqual(len(win), 5)
        self.assertEqual([u.segment for u in win.items_since(0, 0, 60)],
                         [46, 47, 48, 49, 50])


class MessageShape(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.win = window(self.clock)

    def test_empty_history_is_valid_json(self):
        msg = json.loads(self.win.build_history_message(0, 0, 30))
        self.assertEqual(msg, {"type": "HISTORY", "items": []})

    def test_spliced_message_parses_and_is_all_finals(self):
        """The wire form is assembled by string splicing, so parse it back."""
        fill(self.win, self.clock, range(1, 4))
        msg = json.loads(self.win.build_history_message(0, 0, 30))
        self.assertEqual(msg["type"], "HISTORY")
        self.assertEqual([i["segment"] for i in msg["items"]], [1, 2, 3])
        self.assertTrue(all(i["final"] for i in msg["items"]))
        self.assertTrue(all(i["type"] == "CAPTION_UPDATE" for i in msg["items"]))

    def test_message_matches_items_since(self):
        fill(self.win, self.clock, range(1, 8))
        msg = json.loads(self.win.build_history_message(3, 3, 30))
        expected = [u.segment for u in self.win.items_since(3, 3, 30)]
        self.assertEqual([i["segment"] for i in msg["items"]], expected)


class FastPathAgreement(unittest.TestCase):
    """The binary-search path must agree with the linear filter, always.

    `_monotonic` gates an optimisation, so the two code paths have to be proven
    equivalent on the same data rather than assumed equivalent.
    """

    def test_paths_agree_across_many_watermarks(self):
        clock = FakeClock()
        win = window(clock)
        fill(win, clock, range(1, 31))
        self.assertTrue(win.monotonic)

        queries = [(0, 0), (1, 1), (1, 3), (15, 2), (15, 3), (29, 3), (30, 3),
                   (31, 1), (7, 99)]
        fast = {q: [u.segment for u in win.items_since(*q, 60)] for q in queries}

        win._monotonic = False  # force the fallback over identical data
        slow = {q: [u.segment for u in win.items_since(*q, 60)] for q in queries}

        self.assertEqual(fast, slow)

    def test_paths_agree_under_a_time_cutoff(self):
        clock = FakeClock()
        win = window(clock)
        fill(win, clock, range(1, 21))

        fast = [u.segment for u in win.items_since(5, 3, 7)]
        win._monotonic = False
        slow = [u.segment for u in win.items_since(5, 3, 7)]
        self.assertEqual(fast, slow)


class OutOfOrderSource(unittest.TestCase):
    def test_out_of_order_final_latches_off_the_fast_path(self):
        clock = FakeClock()
        metrics = Metrics()
        win = window(clock, metrics=metrics)
        win.record_final(final(5, ts=clock.now))
        clock.advance(1.0)
        win.record_final(final(3, ts=clock.now))  # segment went backwards
        self.assertFalse(win.monotonic)
        self.assertEqual(metrics.get("history_out_of_order"), 1)

    def test_results_are_still_correct_after_latching_off(self):
        clock = FakeClock()
        win = window(clock)
        win.record_final(final(5, ts=clock.now))
        clock.advance(1.0)
        win.record_final(final(3, ts=clock.now))
        clock.advance(1.0)
        win.record_final(final(7, ts=clock.now))
        # Watermark 4 excludes segment 3, keeps 5 and 7, order of arrival kept.
        self.assertEqual([u.segment for u in win.items_since(4, 1, 60)], [5, 7])


class RecoveryGapReporting(unittest.TestCase):
    def test_watermark_inside_the_window_is_not_a_gap(self):
        clock = FakeClock()
        metrics = Metrics()
        win = window(clock, metrics=metrics)
        fill(win, clock, range(1, 11))
        win.build_history_message(4, 3, 60)
        self.assertEqual(metrics.get("history_unrecoverable_gap"), 0)

    def test_watermark_below_the_window_is_counted(self):
        """Offline longer than the window leaves finals nothing can return."""
        clock = FakeClock()
        metrics = Metrics()
        win = window(clock, window_seconds=5.0, metrics=metrics)
        fill(win, clock, range(1, 21))  # window now starts well above segment 2
        win.build_history_message(2, 3, 60)
        self.assertEqual(metrics.get("history_unrecoverable_gap"), 1)

    def test_contiguous_watermark_is_not_counted(self):
        clock = FakeClock()
        metrics = Metrics()
        win = window(clock, window_seconds=5.0, metrics=metrics)
        fill(win, clock, range(1, 21))
        oldest = win.oldest_segment
        win.build_history_message(oldest - 1, 3, 60)
        self.assertEqual(metrics.get("history_unrecoverable_gap"), 0)

    def test_late_join_is_reported_separately_from_a_gap(self):
        clock = FakeClock()
        metrics = Metrics()
        win = window(clock, window_seconds=5.0, metrics=metrics)
        fill(win, clock, range(1, 21))
        win.build_history_message(0, 0, 60)
        self.assertEqual(metrics.get("history_unrecoverable_gap"), 0)
        self.assertEqual(metrics.get("history_late_join_partial"), 1)


if __name__ == "__main__":
    unittest.main()
