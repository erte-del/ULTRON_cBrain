import asyncio
import unittest
from unittest import mock

from tools import registry
from tools.canvas import clear_canvas


class ClearCanvasTest(unittest.TestCase):
    def test_emits_clear_event(self):
        with mock.patch("tools.canvas.hub.emit", new=mock.AsyncMock()) as emit:
            out = asyncio.run(clear_canvas.handler({}))
        emit.assert_awaited_once_with({"type": "canvas.clear"})
        self.assertNotIn("is_error", out)

    def test_registered_as_read(self):
        self.assertIn("mcp__ultron__clear_canvas", registry.auto_allowed())


if __name__ == "__main__":
    unittest.main()
