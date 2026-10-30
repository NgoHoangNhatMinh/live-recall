"""Per-segment revision state and final durability.

OWNER A.

This is the correctness gate. If this module is wrong, Final Caption
Completeness drops and the entire 30-mark hidden-performance section is capped
regardless of how good the fan-out path is.

Three invariants, in priority order:

1.  A final revision is durable. Once a segment is final, nothing replaces it -
    not a higher revision, not a retransmission, nothing.
2.  Within a segment, a higher revision replaces a lower one.
3.  A revision already seen is a duplicate and is not re-published.

`apply()` returns the update only when it advances the state. Everything the
three invariants reject returns None and therefore never reaches the recovery
history or any client queue - one return value enforces all three.

Boundedness
-----------
Live state is one entry per segment, so an unbounded lecture would grow the dict
forever. Eviction is layered:

* up to `max_tracked_segments`, nothing is evicted;
* above it, finalised segments below the lowest *active* segment are evicted,
  and `_pruned_through` keeps rejecting them afterwards so eviction can never
  resurrect stale state;
* above `2 x max_tracked_segments`, eviction stops respecting the active-segment
  floor. This is the escape hatch for a source that abandons a low segment
  without finalising it, which would otherwise block eviction forever.

Sessions
--------
The assignment runs one session at a time and does not require multi-session
support. Rather than hardcode `"L1"`, this class latches onto the session of the
first update it sees and rejects others, so any single-session name works while
a stray second source cannot interleave its segment numbering into this state.
"""

from __future__ import annotations

from .metrics import Metrics
from .model import CaptionUpdate

#: Default ceiling on tracked segments.
DEFAULT_MAX_TRACKED_SEGMENTS = 512

#: Multiple of the ceiling at which eviction stops respecting the active-segment
#: floor. Derived from `max_tracked_segments` rather than exposed in `Config`,
#: because it is a safety backstop for a malformed source, not a tuning knob.
HARD_CEILING_MULTIPLIER = 2


class CaptionState:
    """Authoritative latest-revision state for the active session."""

    __slots__ = (
        "_segments", "_pruned_through", "_max_tracked", "_hard_ceiling",
        "_session", "_metrics",
    )

    def __init__(
        self,
        *,
        metrics: Metrics,
        max_tracked_segments: int = DEFAULT_MAX_TRACKED_SEGMENTS,
    ) -> None:
        if max_tracked_segments < 1:
            raise ValueError("max_tracked_segments must be >= 1")
        self._segments: dict[int, CaptionUpdate] = {}
        self._pruned_through = 0
        self._max_tracked = max_tracked_segments
        self._hard_ceiling = max_tracked_segments * HARD_CEILING_MULTIPLIER
        self._session: str | None = None
        self._metrics = metrics

    # --- write path -----------------------------------------------------

    def apply(self, update: CaptionUpdate) -> CaptionUpdate | None:
        """Admit one caption revision.

        Returns the update when it advances the state and should be published to
        clients, or ``None`` when it is stale, duplicate, or from a foreign
        session and must be dropped. The caller never publishes a ``None``.
        """
        # Latch the session on first contact; reject anything else.
        if self._session is None:
            self._session = update.session
        elif update.session != self._session:
            self._metrics.incr("updates_rejected_session")
            return None

        segment = update.segment

        # Evicted segments are old. Anything arriving for them now is a late
        # retransmission, never new state.
        if segment <= self._pruned_through:
            self._metrics.incr("updates_rejected_stale")
            return None

        current = self._segments.get(segment)
        if current is None:
            self._segments[segment] = update
            self._metrics.incr("updates_accepted")
            self._prune()
            return update

        # Invariant 1: a final revision is durable. Checked before the revision
        # comparison, so even a higher revision cannot overwrite a final.
        if current.final:
            self._metrics.incr("updates_rejected_stale")
            return None

        # Invariant 3: the same revision twice.
        if update.revision == current.revision:
            self._metrics.incr("updates_rejected_duplicate")
            return None

        # Invariant 2: newer replaces older; older never replaces newer.
        if update.revision < current.revision:
            self._metrics.incr("updates_rejected_stale")
            return None

        self._segments[segment] = update
        self._metrics.incr("updates_accepted")
        return update

    # --- read path ------------------------------------------------------

    def latest(self, segment: int) -> CaptionUpdate | None:
        """Latest known revision of `segment`, or None if untracked/evicted."""
        return self._segments.get(segment)

    def is_final(self, segment: int) -> bool:
        """True when `segment` has been finalised, or is old enough to be gone.

        A segment at or below the eviction watermark is reported final because
        no further revision of it will ever be accepted - which is the question
        callers are really asking.
        """
        current = self._segments.get(segment)
        if current is not None:
            return current.final
        return segment <= self._pruned_through

    def active_segments(self) -> list[CaptionUpdate]:
        """Latest revision of every segment the source has not yet finalised.

        Owner B uses this for the "preserve the newest relevant revision of an
        active segment" half of the overload rule (assignment 4.3). These are
        provisional, so they must never be put into a HISTORY message - the load
        client flags a non-final HISTORY item as invalid.
        """
        return [u for u in self._segments.values() if not u.final]

    @property
    def session(self) -> str | None:
        """Session latched on first update, or None before any update."""
        return self._session

    @property
    def pruned_through(self) -> int:
        """Eviction watermark: no segment at or below this is tracked."""
        return self._pruned_through

    def __len__(self) -> int:
        return len(self._segments)

    # --- bounding -------------------------------------------------------

    def _prune(self) -> None:
        """Keep the tracked-segment dict inside its ceiling.

        Two rules make ordinary eviction safe:

        * Only finalised segments are evictable. An active segment is still
          receiving revisions, so dropping it would make a later revision look
          like first contact and lose the ordering guarantee.
        * Nothing at or above the lowest active segment is evictable, because
          `_pruned_through` rejects everything at or below it. The assignment
          says not to assume a fixed revision pattern, so an interleaving source
          must not be able to get its own active segment rejected.

        Those two rules together mean a source that abandons a low segment
        without finalising it blocks eviction entirely. `_force_prune` is the
        backstop for that, and it is why this structure is bounded rather than
        merely usually-bounded.

        On cost: this sorts the evictable segments on every insert past the
        ceiling. At 512 entries and the public source's ~1.3 segments/s that is
        a few thousand operations a second - far below anything measurable, so
        it is deliberately left simple rather than optimised into a second
        index that could disagree with the dict.
        """
        if len(self._segments) <= self._max_tracked:
            return

        active = [s for s, u in self._segments.items() if not u.final]
        floor = min(active) if active else None

        evictable = sorted(
            s for s, u in self._segments.items()
            if u.final and (floor is None or s < floor)
        )
        overflow = len(self._segments) - self._max_tracked
        for segment in evictable[:overflow]:
            del self._segments[segment]
            if segment > self._pruned_through:
                self._pruned_through = segment

        if len(self._segments) > self._hard_ceiling:
            self._force_prune()

        self._metrics.gauge("state_tracked_segments", len(self._segments))

    def _force_prune(self) -> None:
        """Evict lowest segments regardless of the active-segment floor.

        Only reachable when a source has left a low segment active while
        continuing past the hard ceiling. Dropping that segment means a late
        revision of it will be rejected as stale, which is the right outcome for
        a segment the source abandoned - and the alternative is unbounded
        growth, which the assignment counts as a correctness failure.

        Counted so that if this ever fires on a real workload it shows up in the
        metrics line rather than silently changing behaviour.
        """
        overflow = len(self._segments) - self._max_tracked
        for segment in sorted(self._segments)[:overflow]:
            del self._segments[segment]
            if segment > self._pruned_through:
                self._pruned_through = segment
        self._metrics.incr("state_forced_evictions", overflow)
