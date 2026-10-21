import asyncio
import unittest
from unittest import mock

import ui_state
from tools import registry
from tools.ui import change_ui


class UiStateTest(unittest.TestCase):
    def setUp(self):
        ui_state.reset()

    def tearDown(self):
        ui_state.reset()

    def test_adds_on_top_then_replaces_then_resets(self):
        self.assertIsNone(ui_state.apply(".hud { gap: 0 }"))
        self.assertIsNone(ui_state.apply(".panel { opacity: .9 }"))
        self.assertIn("gap: 0", ui_state.css)
        self.assertIn("opacity", ui_state.css)
        self.assertIsNone(ui_state.apply(".x { top: 0 }", replace=True))
        self.assertNotIn("gap", ui_state.css)
        self.assertTrue(ui_state.reset())
        self.assertEqual(ui_state.css, "")
        self.assertFalse(ui_state.reset())

    def test_refuses_loading_and_scripts(self):
        for bad in ("@import 'x.css';", ".a { background: url(https://evil.example/x.png) }",
                    ".a { width: expression(alert(1)) }", "</style><script>"):
            self.assertIsNotNone(ui_state.apply(bad), bad)
        self.assertEqual(ui_state.css, "")
        self.assertIsNone(ui_state.apply(".a { background: url(data:image/png;base64,AAAA) }"))

    def test_comments_do_not_hide_bad_css(self):
        self.assertIsNotNone(ui_state.apply("/* ok */ @import 'x';"))
        self.assertIsNone(ui_state.apply("/* @import 'x'; */ .a { color: red }"))

    def test_unbalanced_and_too_long(self):
        self.assertIsNotNone(ui_state.apply(".a { color: red"))
        self.assertIsNotNone(ui_state.apply(".a { margin: 0 }" * 3000))

    def test_screen_note(self):
        note = ui_state.screen_note({"w": 1440, "h": 900, "sw": 2560, "sh": 1440, "dpr": 2, "voice": False})
        self.assertIn("1440x900", note)
        self.assertIn("wide desktop", note)
        self.assertIn("2560x1440", note)
        self.assertIn("phone layout", ui_state.screen_note({"w": 390, "h": 800}))
        self.assertIn("voice mode", ui_state.screen_note({"w": 1440, "h": 900, "voice": True}))
        for junk in (None, "x", {}, {"w": "a", "h": 1}, {"w": 5, "h": 5}):
            self.assertEqual(ui_state.screen_note(junk), "")


class ChangeUiToolTest(unittest.TestCase):
    def setUp(self):
        ui_state.reset()

    def tearDown(self):
        ui_state.reset()

    def test_sends_the_sheet_and_reset(self):
        with mock.patch("tools.ui.hub.emit", new=mock.AsyncMock(return_value=1)) as emit:
            out = asyncio.run(change_ui.handler({"css": ".hud { gap: 0 }"}))
            emit.assert_awaited_with({"type": "ui.layout", "css": ".hud { gap: 0 }"})
            self.assertNotIn("is_error", out)
            asyncio.run(change_ui.handler({"reset": True}))
            emit.assert_awaited_with({"type": "ui.layout", "css": ""})
        self.assertEqual(ui_state.css, "")

    def test_bad_css_is_an_error_and_changes_nothing(self):
        with mock.patch("tools.ui.hub.emit", new=mock.AsyncMock(return_value=1)) as emit:
            out = asyncio.run(change_ui.handler({"css": "@import 'x';"}))
        self.assertTrue(out["is_error"])
        emit.assert_not_awaited()

    def test_registered_as_read(self):
        self.assertIn("mcp__ultron__change_ui", registry.auto_allowed())


if __name__ == "__main__":
    unittest.main()
