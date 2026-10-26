"""Shared record types and the revision ordering rule.

FROZEN INTERFACE - owners A, B and D all code against this module. Do not
change a signature here without telling the team.

Two decisions are encoded in this file and nowhere else:

1.  A CaptionUpdate carries its own pre-serialised wire form. The fan-out path
    sends `update.wire` directly, so JSON encoding happens once per update
    rather than once per update per client. With 100+ clients this is the
    difference between one encode and a hundred.

2.  `after_watermark()` is the single definition of "strictly newer than the
    state the client already holds". Revision replacement, duplicate
    suppression and reconnect resume must all use it, so that they cannot
    disagree about ordering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

#: Highest recall window a client may request, in seconds (assignment 4.2).
MAX_HISTORY_SECONDS = 60


@dataclass(frozen=True, slots=True)
class CaptionUpdate:
    """One caption revision, normalised and ready to send.

    Instances are immutable. Build them with :meth:`create` rather than calling
    the constructor, so that `wire` can never disagree with the fields.
    """

    session: str
    segment: int
    revision: int
    final: bool
    source_ts: float
    text: str
    wire: str

    @classmethod
    def create(
        cls,
        *,
        session: str,
        segment: int,
        revision: int,
        final: bool,
        source_ts: float,
        text: str,
    ) -> "CaptionUpdate":
        """Normalise one caption revision and pre-serialise its wire form.

        Unrecognised fields from the source are intentionally dropped here. The
        assignment only requires that the server ignore them and keep working,
        and normalising to a known shape keeps the live path and the HISTORY
        path byte-identical for the same revision.
        """
        payload = {
            "type": "CAPTION_UPDATE",
            "session": session,
            "segment": segment,
            "revision": revision,
            "source_ts": source_ts,
            "final": final,
            "text": text,
        }
        return cls(
            session=session,
            segment=segment,
            revision=revision,
            final=final,
            source_ts=source_ts,
            text=text,
            wire=json.dumps(payload, separators=(",", ":")),
        )

    @property
    def key(self) -> tuple[int, int]:
        """`(segment, revision)` - the identity used for dedup and ordering."""
        return (self.segment, self.revision)


@dataclass(frozen=True, slots=True)
class ClientHello:
    """A validated CLIENT_HELLO.

    `history_seconds` is already clamped to [0, MAX_HISTORY_SECONDS], so
    downstream code never has to re-check it.
    """

    client_id: int | str
    session: str
    last_segment: int
    last_revision: int
    history_seconds: int


def after_watermark(
    segment: int,
    revision: int,
    last_segment: int,
    last_revision: int,
) -> bool:
    """True when `(segment, revision)` is strictly newer than the watermark.

    This is the resume semantic the team agreed on: `last_segment` is treated
    as a *watermark*, so anything at or below it is considered already held by
    the client. HISTORY therefore never replays a final the client reported,
    which is what keeps the duplicate-final count at zero.

    The cost of the watermark reading: a client that holds segment 12 but
    missed segment 10 can never recover segment 10, because its watermark hides
    the gap. The overload policy must therefore never create such a gap - every
    final must reach every client in order. See client_session.py.
    """
    if segment > last_segment:
        return True
    return segment == last_segment and revision > last_revision
