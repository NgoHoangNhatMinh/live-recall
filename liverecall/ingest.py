"""Inbound parsing, validation, and the source handler.

Jihan.

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
import math
from typing import TYPE_CHECKING, Any

from .model import MAX_HISTORY_SECONDS, CaptionUpdate, ClientHello

if TYPE_CHECKING:
    from .app import App


class ValidationError(ValueError):
    """Raised for a message that cannot be safely interpreted."""

def _required(msg: dict[str, Any], field: str) -> Any:
    if field not in msg:
        raise ValidationError(f"Missing required field: {field}")
    return msg[field]


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int:
        raise ValidationError(f"{field} must be an integer")
    if value < 1:
        raise ValidationError(f"{field} must be >= 1")
    return value

###The following two helpers are for fields that are optional in the JSON, but
###must be non-negative integers if present.
##The first is for optional fields with a default value, the second is for required fields that must be non-negative integers.
def _non_negative_int(
    value: Any,
    field: str,
    default: int = 0,
) -> int:
    # Retain the helper's optional-default behavior for existing callers.
    if value is None:
        return default
    if type(value) is not int:
        raise ValidationError(f"{field} must be an integer")
    if value < 0:
        raise ValidationError(f"{field} must be >= 0")
    return value

def _required_non_negative_int(
    msg: dict[str, Any],
    field: str,
) -> int:
    value = _required(msg, field)
    # Explicit JSON null is not a valid required integer.
    if value is None:
        raise ValidationError(f"{field} must be an integer")
    return _non_negative_int(value, field)

def _session(value: Any, field: str = "session") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    return value

def _timestamp(value: Any) -> float:
    # Reject booleans and numeric strings as well as NaN/infinity.
    if type(value) not in (int, float):
        raise ValidationError("source_ts must be a number")

    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValidationError(
            "source_ts must be a finite number"
        ) from None

    if not math.isfinite(number):
        raise ValidationError("source_ts must be a finite number")

    return number

def parse_caption_update(
    msg: dict[str, Any],
    default_session: str,
) -> CaptionUpdate:
    """Validate a CAPTION_UPDATE, ignoring unrecognized fields.

    default_session is the session established by SOURCE_HELLO.
    Updates must belong to that session.
    """
    if not isinstance(msg, dict):
        raise ValidationError("Caption update must be a JSON object")

    if msg.get("type") != "CAPTION_UPDATE":
        raise ValidationError("Expected CAPTION_UPDATE")

    session = _session(_required(msg, "session"))
    expected_session = _session(default_session)

    if session != expected_session:
        raise ValidationError(
            "Caption session does not match the source connection"
        )

    segment = _positive_int(_required(msg, "segment"), "segment")
    revision = _positive_int(_required(msg, "revision"), "revision")
    source_ts = _timestamp(_required(msg, "source_ts"))

    final = _required(msg, "final")
    if type(final) is not bool:
        raise ValidationError("final must be a boolean")

    text = _required(msg, "text")
    if not isinstance(text, str):
        raise ValidationError("text must be a string")

    return CaptionUpdate.create(
        session=session,
        segment=segment,
        revision=revision,
        final=final,
        source_ts=source_ts,
        text=text,
    )


def parse_client_hello(
    msg: dict[str, Any],
    default_session: str,
) -> ClientHello:
    """Validate CLIENT_HELLO and cap the requested history window."""
    if not isinstance(msg, dict):
        raise ValidationError("Client hello must be a JSON object")

    if msg.get("type") != "CLIENT_HELLO":
        raise ValidationError("Expected CLIENT_HELLO")

    session = _session(msg.get("session", default_session))

    client_id = _required(msg, "client_id")
    # Allow integer or string identifiers; the assignment does not
    # explicitly restrict client_id to positive integers.
    if type(client_id) not in (int, str):
        raise ValidationError("client_id must be an integer or string")

    last_segment = _required_non_negative_int(msg, "last_segment")
    last_revision = _required_non_negative_int(msg, "last_revision")
    requested = _required_non_negative_int(msg, "history_seconds")

    return ClientHello(
        client_id=client_id,
        session=session,
        last_segment=last_segment,
        last_revision=last_revision,
        history_seconds=min(requested, MAX_HISTORY_SECONDS),
    )


async def handle_source(ws, hello: dict[str, Any], app: "App") -> None:
    """Consume source messages until the connection ends."""
    try:
        if not isinstance(hello, dict):
            raise ValidationError("Source hello must be a JSON object")

        if hello.get("type") != "SOURCE_HELLO":
            raise ValidationError("Expected SOURCE_HELLO")

        session = _session(hello.get("session", app.config.session))

    except ValidationError:
        app.metrics.incr("source_invalid_hello")
        await ws.close(code=1008, reason="Invalid SOURCE_HELLO")
        return

    print(f"source connected: session={session}", flush=True)
    app.metrics.incr("source_connects")

    try:
        async for raw in ws:
            # Preserve the existing counter's meaning: all source
            # messages, including control and invalid messages.
            app.metrics.incr("updates_in")

            try:
                msg = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError):
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

                # Preserve the team's write-path ordering.
                # There is no await between these operations.
                accepted = app.state.apply(update)

                if accepted is None:
                    continue

                if accepted.final:
                    app.history.record_final(accepted)

                app.hub.publish(accepted)

            elif msg_type == "SOURCE_DONE":
                # Control message: never publish it as a caption.
                app.metrics.incr("source_done")
                print(
                    f"source finished: segments={msg.get('segments')}",
                    flush=True,
                )

            else:
                app.metrics.incr("source_unknown_type")
                continue

    finally:
        print("source disconnected", flush=True)
