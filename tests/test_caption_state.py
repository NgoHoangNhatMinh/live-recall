"""Owner A - revision state invariants and boundedness.

Run from the repository root:

    python -m unittest discover -s tests -t .

Stdlib unittest on purpose: `requirements.txt` must stay limited to what
`solution_server.py` needs on the evaluation VM, so the tests add no dependency.
"""

from __future__ import annotations

import unittest

from liverecall.caption_state import CaptionState
from liverecall.metrics import Metrics
from liverecall.model import CaptionUpdate


def upd(segment, revision, *, final=False, session="L1", ts=1000.0, text="t"):
    return CaptionUpdate.create(
        session=session,
        segment=segment,
        revision=revision,
        final=final,
        source_ts=ts,
        text=text,
    )


class RevisionInvariants(unittest.TestCase):
    """The three invariants from the module docstring."""

    def setUp(self):
        self.metrics = Metrics()
        self.state = CaptionState(metrics=self.metrics)

    def test_first_revision_is_accepted(self):
        u = upd(1, 1)
        self.assertIs(self.state.apply(u), u)

    def test_higher_revision_replaces_lower(self):
        self.state.apply(upd(1, 1))
        u2 = upd(1, 2)
        self.assertIs(self.state.apply(u2), u2)
        self.assertEqual(self.state.latest(1).revision, 2)

    def test_same_revision_twice_is_duplicate(self):
        self.state.apply(upd(1, 1))
        self.assertIsNone(self.state.apply(upd(1, 1)))
        self.assertEqual(self.metrics.get("updates_rejected_duplicate"), 1)

    def test_lower_revision_is_stale(self):
        self.state.apply(upd(1, 5))
        self.assertIsNone(self.state.apply(upd(1, 4)))
        self.assertEqual(self.state.latest(1).revision, 5)
        self.assertEqual(self.metrics.get("updates_rejected_stale"), 1)

    def test_final_is_durable_against_higher_revision(self):
        """Invariant 1 outranks invariant 2: even a newer revision loses."""
        self.state.apply(upd(1, 3, final=True))
        self.assertIsNone(self.state.apply(upd(1, 4)))
        self.assertIsNone(self.state.apply(upd(1, 99, final=True)))
        self.assertEqual(self.state.latest(1).revision, 3)
        self.assertTrue(self.state.latest(1).final)

    def test_final_is_durable_against_equal_and_lower(self):
        self.state.apply(upd(1, 3, final=True))
        self.assertIsNone(self.state.apply(upd(1, 3, final=True)))
        self.assertIsNone(self.state.apply(upd(1, 1)))
        self.assertEqual(self.state.latest(1).revision, 3)

    def test_rejected_updates_are_never_returned_for_publication(self):
        """Every rejection path returns None, so nothing stale is published."""
        self.state.apply(upd(1, 2))
        for rejected in (upd(1, 1), upd(1, 2)):
            self.assertIsNone(self.state.apply(rejected))


class ReadPath(unittest.TestCase):
    def setUp(self):
        self.state = CaptionState(metrics=Metrics())

    def test_latest_is_none_for_unknown_segment(self):
        self.assertIsNone(self.state.latest(7))

    def test_is_final_tracks_the_stored_update(self):
        self.state.apply(upd(1, 1))
        self.assertFalse(self.state.is_final(1))
        self.state.apply(upd(1, 2, final=True))
        self.assertTrue(self.state.is_final(1))

    def test_active_segments_excludes_finals(self):
        self.state.apply(upd(1, 1, final=True))
        self.state.apply(upd(2, 1))
        self.state.apply(upd(3, 2))
        self.assertEqual(
            sorted(u.segment for u in self.state.active_segments()), [2, 3]
        )


class SessionHandling(unittest.TestCase):
    def setUp(self):
        self.metrics = Metrics()
        self.state = CaptionState(metrics=self.metrics)

    def test_session_latches_to_first_seen_not_hardcoded(self):
        """Any single-session name works; L1 is not special-cased."""
        self.state.apply(upd(1, 1, session="LECTURE-9"))
        self.assertEqual(self.state.session, "LECTURE-9")

    def test_foreign_session_is_rejected(self):
        self.state.apply(upd(1, 1, session="L1"))
        self.assertIsNone(self.state.apply(upd(2, 1, session="L2")))
        self.assertEqual(self.metrics.get("updates_rejected_session"), 1)
        self.assertIsNone(self.state.latest(2))


class Boundedness(unittest.TestCase):
    def test_rejects_nonsense_ceiling(self):
        with self.assertRaises(ValueError):
            CaptionState(metrics=Metrics(), max_tracked_segments=0)

    def test_eviction_holds_the_ceiling(self):
        state = CaptionState(metrics=Metrics(), max_tracked_segments=4)
        for segment in range(1, 7):
            state.apply(upd(segment, 1, final=True))
        self.assertEqual(len(state), 4)
        self.assertEqual(state.pruned_through, 2)

    def test_evicted_segments_stay_rejected(self):
        """Eviction must not let a stale revision look like first contact."""
        state = CaptionState(metrics=Metrics(), max_tracked_segments=4)
        for segment in range(1, 7):
            state.apply(upd(segment, 1, final=True))
        self.assertIsNone(state.apply(upd(1, 9)))
        self.assertIsNone(state.apply(upd(2, 9, final=True)))
        self.assertNotIn(1, [u.segment for u in state.active_segments()])

    def test_is_final_reports_true_for_evicted_segments(self):
        state = CaptionState(metrics=Metrics(), max_tracked_segments=4)
        for segment in range(1, 7):
            state.apply(upd(segment, 1, final=True))
        self.assertTrue(state.is_final(1))

    def test_active_segment_is_never_evicted_by_normal_pruning(self):
        """An interleaving source must not get its own active segment rejected."""
        state = CaptionState(metrics=Metrics(), max_tracked_segments=4)
        state.apply(upd(1, 1))  # stays provisional
        for segment in range(2, 7):
            state.apply(upd(segment, 1, final=True))
        self.assertEqual(state.pruned_through, 0)
        self.assertIsNotNone(state.latest(1))
        # And it can still be advanced and finalised.
        self.assertIsNotNone(state.apply(upd(1, 2, final=True)))

    def test_abandoned_active_segment_cannot_grow_without_bound(self):
        """The hard ceiling is what makes this bounded, not merely usually so."""
        metrics = Metrics()
        state = CaptionState(metrics=metrics, max_tracked_segments=4)
        state.apply(upd(1, 1))  # abandoned: never finalised
        for segment in range(2, 40):
            state.apply(upd(segment, 1, final=True))
            self.assertLessEqual(len(state), 8, "hard ceiling breached")
        self.assertGreater(metrics.get("state_forced_evictions"), 0)
        # The abandoned segment is gone, and late revisions of it are stale.
        self.assertIsNone(state.latest(1))
        self.assertIsNone(state.apply(upd(1, 2)))


if __name__ == "__main__":
    unittest.main()
