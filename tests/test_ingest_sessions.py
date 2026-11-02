import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from liverecall.ingest import (
    ValidationError,
    handle_source,
    parse_caption_update,
    parse_client_hello,
)
from liverecall.metrics import Metrics


def caption(session):
    return {
        "type": "CAPTION_UPDATE",
        "session": session,
        "segment": 1,
        "revision": 1,
        "source_ts": 1760000000.123,
        "final": True,
        "text": "Hello",
    }


class FakeWebSocket:
    """Simulate incoming messages without opening a real connection."""

    def __init__(self, messages):
        self.messages = iter(json.dumps(msg) for msg in messages)
        self.close = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration


def make_app():
    return SimpleNamespace(
        config=SimpleNamespace(session="L1"),
        metrics=Metrics(),
        state=SimpleNamespace(
            apply=Mock(side_effect=lambda update: update),
        ),
        history=SimpleNamespace(record_final=Mock()),
        hub=SimpleNamespace(publish=Mock()),
    )


class SessionParserTests(unittest.TestCase):
    def test_caption_accepts_matching_non_default_session(self):
        result = parse_caption_update(caption("L2"), "L2")
        self.assertEqual(result.session, "L2")

    def test_caption_rejects_mismatched_session(self):
        with self.assertRaises(ValidationError):
            parse_caption_update(caption("L3"), "L2")

    def test_client_keeps_explicit_session(self):
        msg = {
            "type": "CLIENT_HELLO",
            "client_id": 17,
            "session": "L2",
            "last_segment": 0,
            "last_revision": 0,
            "history_seconds": 30,
        }
        result = parse_client_hello(msg, "L1")
        self.assertEqual(result.session, "L2")

    def test_client_uses_fallback_when_session_missing(self):
        msg = {
            "type": "CLIENT_HELLO",
            "client_id": 17,
            "last_segment": 0,
            "last_revision": 0,
            "history_seconds": 30,
        }
        result = parse_client_hello(msg, "L1")
        self.assertEqual(result.session, "L1")


class SourceSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_accepts_explicit_non_default_session(self):
        app = make_app()
        ws = FakeWebSocket([caption("L2")])

        await handle_source(
            ws,
            {"type": "SOURCE_HELLO", "session": "L2"},
            app,
        )

        ws.close.assert_not_awaited()
        app.hub.publish.assert_called_once()
        update = app.hub.publish.call_args.args[0]
        self.assertEqual(update.session, "L2")
        app.history.record_final.assert_called_once_with(update)

    async def test_source_uses_fallback_when_session_missing(self):
        app = make_app()
        ws = FakeWebSocket([caption("L1")])

        await handle_source(ws, {"type": "SOURCE_HELLO"}, app)

        ws.close.assert_not_awaited()
        app.hub.publish.assert_called_once()
        update = app.hub.publish.call_args.args[0]
        self.assertEqual(update.session, "L1")

    async def test_bad_session_does_not_block_next_valid_update(self):
        app = make_app()
        ws = FakeWebSocket([
            caption("L3"),  # Wrong session: reject.
            caption("L2"),  # Correct session: still process.
        ])

        await handle_source(
            ws,
            {"type": "SOURCE_HELLO", "session": "L2"},
            app,
        )

        self.assertEqual(
            app.metrics.get("source_invalid_update"), 1
        )
        app.state.apply.assert_called_once()
        app.hub.publish.assert_called_once()
        update = app.hub.publish.call_args.args[0]
        self.assertEqual(update.session, "L2")


if __name__ == "__main__":
    unittest.main()