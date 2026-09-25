"""Offline regression for HTTP-200 corrupt screenshot recovery."""

from __future__ import annotations

import io
import pathlib
import sys
import unittest
from unittest import mock

from PIL import Image


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "OSWorld"))

from gui_rewalk.env.osworld_reload import PythonController  # noqa: E402


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (12, 8), (20, 40, 60)).save(stream, format="PNG")
    return stream.getvalue()


class _Response:
    def __init__(self, content: bytes, *, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": "image/png"}
        self.text = ""


class ScreenshotPayloadRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = PythonController("127.0.0.1", 5000)
        self.controller.retry_times = 3
        self.controller.retry_interval = 0

    def test_payload_validation_rejects_empty_html_and_truncated_png(self):
        valid = _png_bytes()
        self.assertTrue(self.controller._is_valid_screenshot_payload(valid))
        self.assertFalse(self.controller._is_valid_screenshot_payload(b""))
        self.assertFalse(self.controller._is_valid_screenshot_payload(b"<html>busy</html>"))
        self.assertFalse(self.controller._is_valid_screenshot_payload(valid[:24]))

    def test_http_200_corrupt_payload_is_retried_until_valid(self):
        valid = _png_bytes()
        responses = [
            _Response(b"<html>busy</html>"),
            _Response(valid[:24]),
            _Response(valid),
        ]
        with mock.patch(
            "gui_rewalk.env.osworld_reload.requests.get",
            side_effect=responses,
        ) as get, mock.patch.object(self.controller, "_note_ok") as note_ok:
            result = self.controller.get_screenshot()

        self.assertEqual(result, valid)
        self.assertEqual(get.call_count, 3)
        note_ok.assert_called_once_with()

    def test_all_corrupt_payloads_fail_and_run_diagnosis(self):
        with mock.patch(
            "gui_rewalk.env.osworld_reload.requests.get",
            return_value=_Response(b"not an image"),
        ) as get, mock.patch.object(
            self.controller, "_diagnose_screenshot_failure"
        ) as diagnose, mock.patch.object(self.controller, "_note_ok") as note_ok:
            result = self.controller.get_screenshot()

        self.assertIsNone(result)
        self.assertEqual(get.call_count, 3)
        note_ok.assert_not_called()
        diagnose.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
