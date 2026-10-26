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

The implementation below is correct but deliberately plain. Owner A hardens the
edge cases; the signatures are what B and D build against.
"""

from __future__ import annotations

from .metrics import Metrics
from .model import CaptionUpdate

#: Default ceiling on tracked segments. Live state is per-segment, so without a
#: ceiling a long lecture grows the dict forever - a boundedness violation even
#: though each entry is small. Evicted segments stay rejected via the
#: `_pruned_through` watermark, so eviction cannot resurrect stale revisions.
DEFAULT_MAX_TRACKED_SEGMENTS = 512


class CaptionState:
    """Authoritative latest-revision state for the active session."""

    __slots__ = ("_segments", "_pruned_through", "_max_tracked", "_metrics")

    def __init__(
        self,
        *,
        metrics: Metrics,
        max_tracked_segments: int = DEFAULT_MAX_TRACKED_SEGMENTS,
    ) -> None:
        self._segments: dict[int, CaptionUpdate] = {}
        self._pruned_through = 0
        self._max_tracked = max_tracked_segments
        self._metrics = metrics

    # --- write path -----------------------------------------------------

    def apply(self, update: CaptionUpdate) -> CaptionUpdate | None:
        """Admit one caption revision.

        Returns the update when it advances the state and should be published
        to clients, or ``None`` when it is stale or a duplicate and must be
        dropped. The caller never publishes a ``None``.
        """
        segment = update.segment

        # Evicted segments are finalised and old. Anything arriving for them now
        # is a late retransmission, never new state.
        if segment <= self._pruned_through:
            self._metrics.incr("updates_rejected_stale")
            return None

        current = self._segments.get(segment)
        if current is None:
            self._segments[segment] = update
            self._metrics.incr("updates_accepted")
            self._prune()
            return update

        # Invariant 1: a final revision is durable.
        if current.final:
            self._metrics.incr("updates_rejected_stale")
            return None

        # Invariant 3: same revision twice.
        if update.revision == current.revision:
            self._metrics.incr("updates_rejected_duplicate")
            return None

        # Invariant 2: newer revision replaces older; older never replaces newer.
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
        """True when `segment` has been finalised by the source."""
        current = self._segments.get(segment)
        if current is not None:
            return current.final
        # Evicted segments were only evicted because they were final.
        return segment <= self._pruned_through

    def active_segments(self) -> list[CaptionUpdate]:
        """Latest revision of every segment the source has not yet finalised.

        Owner B uses this for the "preserve the newest relevant revision of an
        active segment" half of the overload rule (assignment 4.3). These are
        provisional, so they must never be put into a HISTORY message - the
        load client flags a non-final HISTORY item as invalid.
        """
        return [u for u in self._segments.values() if not u.final]

    def __len__(self) -> int:
        return len(self._segments)

    # --- bounding -------------------------------------------------------

    def _prune(self) -> None:
        """Evict the oldest finalised segments once over the tracking ceiling.

        Two restrictions keep eviction safe:

        * Only finalised segments are evictable. An active segment is still
          receiving revisions, so dropping it would make a later revision look
          like first contact and lose the ordering guarantee.
        * Nothing at or above the lowest active segment is evictable, because
          `_pruned_through` rejects everything below it. The assignment says not
          to assume a fixed revision pattern, so an interleaving source must not
          be able to get its own active segment rejected.

        Consequence worth knowing: a source that leaves a low segment active
        forever blocks eviction and the dict can exceed the ceiling. The public
        and instructor sources complete a segment before starting the next, so
        this cannot happen there. TODO(A): decide whether to force-finalise a
        long-abandoned active segment if we ever see such a source.
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
        self._metrics.gauge("state_tracked_segments", len(self._segments))
