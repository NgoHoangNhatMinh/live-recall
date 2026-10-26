"""Client registry and fan-out.

OWNER B.

`publish()` is the hottest path in the server: it runs once per accepted
revision and touches every connected client. Two rules keep it cheap:

* it is synchronous - it hands each session a frame and returns, so the source
  task is never blocked by a socket;
* it does no per-client serialisation - each `CaptionUpdate` already carries its
  wire form (see model.py), so fan-out is a loop of appends.

Sessions are duck-typed rather than imported, which keeps hub.py free of an
import cycle with client_session.py. A session needs `offer()`, `close()` and
`client_id`.
"""

from __future__ import annotations

from .metrics import Metrics
from .model import CaptionUpdate


class Hub:
    """The set of clients currently eligible for live updates."""

    __slots__ = ("_sessions", "_metrics")

    def __init__(self, *, metrics: Metrics) -> None:
        self._sessions: set = set()
        self._metrics = metrics

    def add(self, session) -> None:
        """Register a session for live updates.

        Must be called synchronously and immediately after the client's HISTORY
        frame is built - see the ordering note in client_session.serve_client.
        """
        self._sessions.add(session)
        self._metrics.gauge("clients_connected", len(self._sessions))
        self._metrics.peak("clients_connected", len(self._sessions))
        self._metrics.incr("client_connects")

    def remove(self, session) -> None:
        self._sessions.discard(session)
        self._metrics.gauge("clients_connected", len(self._sessions))
        self._metrics.incr("client_disconnects")

    def publish(self, update: CaptionUpdate) -> None:
        """Offer one accepted revision to every connected client."""
        if not self._sessions:
            return
        # A session may close itself from inside offer() when it hits its hard
        # bound. That only marks the session closed - deregistration happens in
        # its own connection handler - so iteration is safe. The snapshot is
        # cheap insurance against a future change making offer() deregister.
        for session in tuple(self._sessions):
            session.offer(update)
        self._metrics.incr("updates_published")

    def close_all(self) -> None:
        for session in tuple(self._sessions):
            session.close()
        self._sessions.clear()
        self._metrics.gauge("clients_connected", 0)

    def __len__(self) -> int:
        return len(self._sessions)
