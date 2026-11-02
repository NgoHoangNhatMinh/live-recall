"""Configuration and the dependency container.

FROZEN INTERFACE - every handler receives an `App` and reaches its collaborators
through it. Keeping the wiring in one place means `solution_server.py` stays a
thin entry point and no owner has to edit another owner's module to get hold of
a dependency.

The bound values below are the team's day-one decisions. They are deliberately
all in one place so that the report can quote them and the viva can defend
them. Tune the numbers; do not scatter new ones through the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass

from .caption_state import CaptionState
from .history import HistoryWindow
from .hub import Hub
from .metrics import Metrics


@dataclass(frozen=True, slots=True)
class Config:
    """Every tunable bound in the server.

    Boundedness is part of correctness in this assignment, so each field below
    answers the question "what stops this growing forever?".
    """

    #: Session the mandatory tests use. One active session at a time (4.1).
    session: str = "L1"

    #: Seconds a connection has to send its hello before we close it.
    hello_timeout: float = 5.0

    # --- live revision state bounds (owner A) ---------------------------
    #: Ceiling on segments tracked for revision comparison. Finalised segments
    #: below the lowest active one are evicted past this point; the eviction
    #: watermark keeps rejecting them, so eviction cannot resurrect stale state.
    state_max_tracked_segments: int = 512

    # --- history bounds (owner A) ---------------------------------------
    #: Age cutoff for retained finalised captions. Must exceed the 60 s recall
    #: requirement with slack, so a client asking for 60 s is always satisfied.
    history_window_seconds: float = 90.0
    #: Hard ceiling on retained finals, independent of the clock. Protects
    #: against a source that emits segments far faster than the public one.
    history_max_items: int = 1500

    # --- per-client queue bounds (owner B) ------------------------------
    #: Soft bound. Above this depth the overload policy starts shedding or
    #: coalescing obsolete provisional revisions.
    queue_soft_limit: int = 32
    #: Hard bound. A client still over this after the policy has run is
    #: disconnected; it reconnects and resumes cleanly through HISTORY, which
    #: is cheaper than letting it drag an ever-staler backlog.
    queue_hard_limit: int = 128

    # --- lag detection and overload hysteresis (owner B) -----------------
    #: Queueing delay, measured by ping/pong above the connection's baseline
    #: RTT, at which a client is treated as overloaded. Well above anything a
    #: healthy client sees, but small next to the 500 ms freshness threshold.
    overload_lag_high: float = 0.25
    #: Queueing delay a client must stay under before overload clears.
    overload_lag_low: float = 0.08
    #: Seconds a client must stay calm before overload clears. Stops the
    #: policy flapping on and off every few frames.
    overload_clear_hold: float = 2.0
    #: Frames an overloaded client may have unconfirmed in flight. Anything
    #: past this waits in our queue, where it can still be coalesced, instead
    #: of in kernel buffers, where it cannot.
    overload_inflight_frames: int = 3
    #: Seconds between lag probes for a client that is keeping up.
    probe_interval: float = 0.5

    # --- observability (owner D) ----------------------------------------
    #: Seconds between metric log lines. 0 disables periodic logging.
    metrics_interval_seconds: float = 5.0


class App:
    """Holds the server's long-lived collaborators.

    Construction order matters: metrics first (everything reports into it),
    then the state and history owned by A, then B's fan-out hub.
    """

    __slots__ = ("config", "metrics", "state", "history", "hub")

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.metrics = Metrics()
        self.state = CaptionState(
            metrics=self.metrics,
            max_tracked_segments=self.config.state_max_tracked_segments,
        )
        self.history = HistoryWindow(
            window_seconds=self.config.history_window_seconds,
            max_items=self.config.history_max_items,
            metrics=self.metrics,
        )
        self.hub = Hub(metrics=self.metrics)
