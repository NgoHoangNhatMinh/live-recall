"""Inbound parsing, validation, and the source handler.

OWNER D.

All untrusted input enters the server here. Everything downstream works with
validated `CaptionUpdate` / `ClientHello` records and never re-checks a field,
so validation has to be complete at this boundary.

Two spec rules shape the validation:

* unrecognised JSON fields must be ignored and the server must keep operating
  (4.1) - the instructor source may add a test-phase label, and crashing on it
  would be a zero;
* `revision` counts are not fixed, so nothing may assume three revisions per
  segment.

`handle_source` is also where the ordering of the write path lives, and that
ordering is the correctness gate: admit, then record, then publish.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .model import MAX_HISTORY_SECONDS, CaptionUpdate, ClientHello

if TYPE_CHECKING:
    from .app import App


class ValidationError(ValueError):
    """Raised for a message that cannot be safely interpreted."""


def _positive_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer, got {value!r}") from None
    if number < 1:
        raise ValidationError(f"{field} must be >= 1, got {number}")
    return number


def _non_negative_int(value: Any, field: str, default: int = 0) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer, got {value!r}") from None
    return max(0, number)


def parse_caption_update(msg: dict[str, Any], default_session: str) -> CaptionUpdate:
    """Validate one CAPTION_UPDATE and normalise it.

    Raises ValidationError rather than returning None, so a malformed update can
    be counted and logged instead of silently vanishing.
    """
    segment = _positive_int(msg.get("segment"), "segment")
    revision = _positive_int(msg.get("revision"), "revision")

    try:
        source_ts = float(msg["source_ts"])
    except (KeyError, TypeError, ValueError):
        raise ValidationError("source_ts must be a number") from None

    text = msg.get("text", "")
    if not isinstance(text, str):
        raise ValidationError("text must be a string")

    return CaptionUpdate.create(
        session=msg.get("session") or default_session,
        segment=segment,
        revision=revision,
        final=bool(msg.get("final")),
        source_ts=source_ts,
        text=text,
    )


def parse_client_hello(msg: dict[str, Any], default_session: str) -> ClientHello:
    """Validate one CLIENT_HELLO and clamp its recall request.

    A client with no prior state sends `last_segment=0, last_revision=0` (4.2),
    so zero is valid here - unlike a caption's segment number. `history_seconds`
    is clamped to the 60 s ceiling once, here, so no caller repeats the check.
    """
    requested = _non_negative_int(msg.get("history_seconds"), "history_seconds", 30)
    return ClientHello(
        client_id=msg.get("client_id", "unknown"),
        session=msg.get("session") or default_session,
        last_segment=_non_negative_int(msg.get("last_segment"), "last_segment"),
        last_revision=_non_negative_int(msg.get("last_revision"), "last_revision"),
        history_seconds=min(requested, MAX_HISTORY_SECONDS),
    )


async def handle_source(ws, hello: dict[str, Any], app: "App") -> None:
    """Consume the caption source for the lifetime of its connection."""
    session = hello.get("session") or app.config.session
    print(f"source connected: session={session}", flush=True)
    app.metrics.incr("source_connects")

    try:
        async for raw in ws:
            app.metrics.incr("updates_in")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                app.metrics.incr("source_bad_json")
                continue
            if not isinstance(msg, dict):
                app.metrics.incr("source_bad_json")
                continue

            msg_type = msg.get("type")

            if msg_type == "CAPTION_UPDATE":
                try:
                    update = parse_caption_update(msg, session)
                except ValidationError:
                    app.metrics.incr("source_invalid_update")
                    continue

                # Write-path ordering, and it matters:
                #   1. admit - stale and duplicate revisions stop here, so they
                #      never reach history or any client queue;
                #   2. record - a final enters the recovery window *before* it
                #      is published, so a client reconnecting in the same
                #      instant finds it rather than missing it;
                #   3. publish - hand it to every client queue, without ever
                #      awaiting a socket.
                accepted = app.state.apply(update)
                if accepted is None:
                    continue
                if accepted.final:
                    app.history.record_final(accepted)
                app.hub.publish(accepted)

            elif msg_type == "SOURCE_DONE":
                # Test-control message. Not forwarded to clients (4.1).
                app.metrics.incr("source_done")
                print(
                    f"source finished: segments={msg.get('segments')}",
                    flush=True,
                )

            else:
                # Forward compatibility: ignore message types and fields this
                # server does not know, rather than failing the connection.
                app.metrics.incr("source_unknown_type")
                continue
    finally:
        print("source disconnected", flush=True)
