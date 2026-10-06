"""The Windows PC: the real windows/ultron_pc.py server on 127.0.0.1, driven by pc_read/pc_change.
Only the cross-platform parts run here (token, folder fence, no overwrites, unreachable PC).
    .venv/bin/python -m unittest tests.test_pc
"""

import asyncio
import subprocess
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
        self.assertEqual(call(pc.pc_run, code="print('şğü')"), ("şğü", False))

    def test_pc_side_crash_is_an_answer(self):  # status needs Windows: here it fails, but answers
        text, err = call(pc.pc_read, what="status")
        self.assertTrue(err)
        self.assertNotIn("isn't reachable", text)

    def test_open_app_matches_part_of_the_name(self):
        apps = '[{"Name": "Google Chrome", "AppID": "chrome"}, {"Name": "Unity Hub", "AppID": "unity"}]'
        with mock.patch.object(agent, "ps", return_value=apps), mock.patch.object(agent.subprocess, "Popen") as popen:
            self.assertEqual(agent.open_app("chrome"), "Opened Google Chrome.")
            self.assertEqual(agent.open_app("unity hub"), "Opened Unity Hub.")
            self.assertEqual(popen.call_count, 2)
            self.assertRaises(ValueError, agent.open_app, "photoshop")

    def test_open_app_falls_back_to_desktop_shortcuts(self):
        desktop = self.root.parent / "Desktop"
        desktop.mkdir()
        (desktop / "Rocket League®.url").write_text("[InternetShortcut]\nURL=com.epicgames.launcher://x")
        with mock.patch.object(agent, "ps", return_value="[]"), \
                mock.patch.object(agent, "user_dirs", return_value={"Desktop": desktop}), \
                mock.patch.object(agent.os, "startfile", create=True) as start:
            self.assertEqual(agent.open_app("rocket league"), "Opened Rocket League® from the Desktop.")
            start.assert_called_once_with(desktop / "Rocket League®.url")
            self.assertRaises(ValueError, agent.open_app, "photoshop")

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

    def test_user_folders_content_and_approval(self):
        desktop = self.root.parent / "Desktop"
        desktop.mkdir()
        (desktop / "notes.txt").write_text("hello from the PC")
        with mock.patch.object(agent, "user_dirs", return_value={"Desktop": desktop}):
            text, err = call(pc.pc_read, what="files", query="notes", folder="Desktop")
            self.assertIn("notes.txt", text)
            path = str(desktop / "notes.txt")
            self.assertIn("hello from the PC", call(pc.pc_read, what="content", path=path)[0])
            move = {"action": "move", "path": path, "to": "notes.txt"}
            self.assertTrue(registry.needs_ok("mcp__ultron__pc_change", move))
            self.assertFalse(registry.needs_ok("mcp__ultron__pc_change", {"action": "move", "path": "a", "to": "b/c"}))
            self.assertTrue(pc.leaves_folder({"action": "trash", "path": "x\\..\\..\\Desktop\\y"}))
            # the PC itself refuses outside its folder unless pc_change says the user approved
            self.assertFalse(call(pc.pc_change, action="move", path=path, to="notes.txt")[1])  # approved
            self.assertRaises(ValueError, agent.move, "notes.txt", str(desktop / "n.txt"))  # not approved
            self.assertTrue((self.root / "notes.txt").exists())
        from tools.spotify import phone_of
        devices = [{"id": "m", "type": "Computer", "name": "MacBook"}, {"id": "p", "type": "Computer", "name": "DESKTOP-1"}]
        self.assertEqual(phone_of(devices, "desktop-1")["id"], "p")
        self.assertIsNone(phone_of(devices, "other"))

    def test_bad_input(self):
        self.assertTrue(call(pc.pc_change, action="open_url", url="file:///C:/Windows")[1])
        self.assertTrue(call(pc.pc_change, action="format_disk")[1])

    def test_update_pulls_new_code(self):
        def git(*args, cwd):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                           capture_output=True)
        origin, clone = self.root.parent / "origin", self.root.parent / "clone"
        origin.mkdir()
        git("init", "-q", "-b", "main", cwd=origin)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=origin)
        git("clone", "-q", str(origin), str(clone), cwd=origin)
        with mock.patch.object(agent, "REPO", clone):
            self.assertFalse(agent.update())  # nothing new
            git("commit", "-q", "--allow-empty", "-m", "two", cwd=origin)
            self.assertTrue(agent.update())
            (clone / "f").write_text("local"); git("add", "f", cwd=clone); git("commit", "-q", "-m", "mine", cwd=clone)
            git("commit", "-q", "--allow-empty", "-m", "three", cwd=origin)
            self.assertFalse(agent.update())  # diverged: keeps running what it has
        with mock.patch.object(agent, "REPO", self.root.parent / "nowhere"):
            self.assertFalse(agent.update())

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
