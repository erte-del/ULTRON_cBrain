"""The Windows PC: the real windows/ultron_pc.py server on 127.0.0.1, driven by pc_read/pc_change.
Only the cross-platform parts run here (token, folder fence, no overwrites, unreachable PC).
    .venv/bin/python -m unittest tests.test_pc
"""

import asyncio
import importlib.util
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

import config
from tools import pc, registry

spec = importlib.util.spec_from_file_location("ultron_pc", Path(__file__).parents[2] / "windows" / "ultron_pc.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def call(handler, **args):
    result = asyncio.run(handler.handler(args))
    return result["content"][0]["text"], bool(result.get("is_error"))


class PcTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "Ultron"
        server = HTTPServer(("127.0.0.1", 0), agent.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for patch in [mock.patch.object(agent, "FOLDER", self.root), mock.patch.object(agent, "TOKEN", "t" * 32),
                      mock.patch.object(config, "PC_URL", f"http://127.0.0.1:{server.server_port}"),
                      mock.patch.object(config, "PC_TOKEN", "t" * 32)]:
            patch.start()
            self.addCleanup(patch.stop)

    def test_labels(self):
        self.assertEqual(registry.classify("mcp__ultron__pc_read"), "read")
        self.assertEqual(registry.classify("mcp__ultron__pc_change"), "act")
        self.assertFalse(registry.needs_ok("mcp__ultron__pc_change", {"action": "mute"}))
        self.assertTrue(registry.needs_ok("mcp__ultron__pc_run", {"code": "print(1)"}))

    def test_run_python_in_output(self):
        self.assertEqual(call(pc.pc_run, code="import os; print(os.path.basename(os.getcwd()))"), ("Output", False))
        text, err = call(pc.pc_run, code="raise SystemExit(3)")
        self.assertTrue(err)
        self.assertTrue(call(pc.pc_run, code="x", lang="bash")[1])

    def test_files_and_move_inside_the_fence(self):
        self.root.mkdir()
        (self.root / "a.txt").write_text("x")
        (self.root / "b.txt").write_text("y")
        text, err = call(pc.pc_read, what="files", query="a")
        self.assertFalse(err)
        self.assertIn("a.txt", text)
        self.assertEqual(call(pc.pc_change, action="move", path="a.txt", to="Docs/a.txt"),
                         ("Moved a.txt → Docs/a.txt.", False))
        self.assertTrue(call(pc.pc_change, action="move", path="b.txt", to="Docs/a.txt")[1])  # no overwrite
        self.assertTrue(call(pc.pc_change, action="move", path="b.txt", to="../b.txt")[1])  # no escape
        self.assertTrue((self.root / "b.txt").exists())

    def test_bad_input(self):
        self.assertTrue(call(pc.pc_change, action="open_url", url="file:///C:/Windows")[1])
        self.assertTrue(call(pc.pc_change, action="format_disk")[1])

    def test_wrong_token(self):
        with mock.patch.object(config, "PC_TOKEN", "wrong"):
            self.assertEqual(call(pc.pc_read, what="files"), ("Wrong or missing token.", True))
        self.assertFalse(self.root.exists())  # refused before touching anything

    def test_unreachable_and_not_set_up(self):
        with mock.patch.object(config, "PC_URL", "http://127.0.0.1:1"):
            self.assertIn("isn't reachable", call(pc.pc_read, what="status")[0])
        with mock.patch.object(config, "PC_URL", ""):
            self.assertIn("isn't set up", call(pc.pc_read, what="status")[0])


if __name__ == "__main__":
    unittest.main()
