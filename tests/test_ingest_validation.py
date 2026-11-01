import unittest

from liverecall.ingest import (
    ValidationError,
    parse_caption_update,
    parse_client_hello,
)
from liverecall.model import MAX_HISTORY_SECONDS


class CaptionValidationTests(unittest.TestCase):
    def valid_message(self):
        return {
            "type": "CAPTION_UPDATE",
            "session": "L1",
            "segment": 1,
            "revision": 2,
            "source_ts": 1760000000.123,
            "final": False,
            "text": "Today we study TCP",
        }

    def test_valid_caption(self):
        result = parse_caption_update(self.valid_message(), "L1")
        self.assertEqual(result.segment, 1)
        self.assertEqual(result.revision, 2)
        self.assertFalse(result.final)
        self.assertEqual(result.text, "Today we study TCP")

    def test_true_final_is_preserved(self):
        msg = self.valid_message()
        msg["final"] = True
        self.assertTrue(parse_caption_update(msg, "L1").final)

    def test_unknown_fields_are_ignored(self):
        msg = self.valid_message()
        msg["test_phase"] = "normal"
        result = parse_caption_update(msg, "L1")
        self.assertEqual(result.segment, 1)

    def test_revision_count_is_not_fixed(self):
        msg = self.valid_message()
        msg["revision"] = 100
        result = parse_caption_update(msg, "L1")
        self.assertEqual(result.revision, 100)

    def test_invalid_segment_and_revision(self):
        for field in ("segment", "revision"):
            for value in (0, -1, 1.5, True, "2", None):
                with self.subTest(field=field, value=value):
                    msg = self.valid_message()
                    msg[field] = value
                    with self.assertRaises(ValidationError):
                        parse_caption_update(msg, "L1")

    def test_final_must_be_boolean(self):
        for value in ("false", "true", 0, 1, None):
            with self.subTest(value=value):
                msg = self.valid_message()
                msg["final"] = value
                with self.assertRaises(ValidationError):
                    parse_caption_update(msg, "L1")

    def test_timestamp_must_be_finite_number(self):
        for value in (
            "1760000000.123",
            True,
            None,
            float("nan"),
            float("inf"),
            float("-inf"),
            10 ** 400,
        ):
            with self.subTest(value=value):
                msg = self.valid_message()
                msg["source_ts"] = value
                with self.assertRaises(ValidationError):
                    parse_caption_update(msg, "L1")

    def test_required_fields_cannot_be_missing(self):
        for field in self.valid_message():
            with self.subTest(field=field):
                msg = self.valid_message()
                del msg[field]
                with self.assertRaises(ValidationError):
                    parse_caption_update(msg, "L1")

    def test_invalid_session(self):
        for value in ("L2", "", [], 123):
            with self.subTest(value=value):
                msg = self.valid_message()
                msg["session"] = value
                with self.assertRaises(ValidationError):
                    parse_caption_update(msg, "L1")

    def test_invalid_text(self):
        msg = self.valid_message()
        msg["text"] = 123
        with self.assertRaises(ValidationError):
            parse_caption_update(msg, "L1")

    def test_empty_text_is_allowed(self):
        msg = self.valid_message()
        msg["text"] = ""
        self.assertEqual(parse_caption_update(msg, "L1").text, "")


class ClientHelloValidationTests(unittest.TestCase):
    def valid_message(self):
        return {
            "type": "CLIENT_HELLO",
            "client_id": 17,
            "session": "L1",
            "last_segment": 0,
            "last_revision": 0,
            "history_seconds": 30,
        }

    def test_first_connection(self):
        result = parse_client_hello(self.valid_message(), "L1")
        self.assertEqual(result.last_segment, 0)
        self.assertEqual(result.last_revision, 0)
        self.assertEqual(result.history_seconds, 30)

    def test_resume_position_is_preserved(self):
        msg = self.valid_message()
        msg["last_segment"] = 38
        msg["last_revision"] = 3
        result = parse_client_hello(msg, "L1")
        self.assertEqual(result.last_segment, 38)
        self.assertEqual(result.last_revision, 3)

    def test_history_is_capped(self):
        msg = self.valid_message()
        msg["history_seconds"] = MAX_HISTORY_SECONDS + 100
        result = parse_client_hello(msg, "L1")
        self.assertEqual(result.history_seconds, MAX_HISTORY_SECONDS)

    def test_invalid_recovery_fields(self):
        for field in ("last_segment", "last_revision", "history_seconds"):
            for value in (-1, 1.5, True, "30", None):
                with self.subTest(field=field, value=value):
                    msg = self.valid_message()
                    msg[field] = value
                    with self.assertRaises(ValidationError):
                        parse_client_hello(msg, "L1")


if __name__ == "__main__":
    unittest.main()