"""The terminal tab's shell (/ws/terminal). Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
import terminal
from tools.canvas import read_terminal


class TerminalTest(unittest.TestCase):
    def setUp(self):
        # uvloop, like uvicorn: it starts subprocesses differently from plain asyncio.
        self.client = TestClient(main.app, backend_options={"use_uvloop": True})

    @unittest.skipIf(sys.platform == "win32", "no shell tab on Windows")
    def test_runs_what_you_type(self):
        # A plain shell: the test shouldn't depend on your zsh profile.
        with mock.patch.dict(os.environ, {"SHELL": "/bin/sh", "ANTHROPIC_BASE_URL": "http://gateway"}):
            with self.client.websocket_connect("/ws/terminal", headers={"origin": "http://127.0.0.1:8000"}) as ws:
                ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
                ws.send_text(json.dumps({"type": "input", "data": 'echo "[$((6*7))] [$ANTHROPIC_BASE_URL]"; stty size; exit\n'}))
                out = b""
                try:
                    while True:
                        out += ws.receive_bytes()
                except WebSocketDisconnect:  # `exit` closes the tab's connection
                    pass
        text = out.decode()
        self.assertIn("[42] []", text)  # ran, and without the gateway variables
        self.assertIn("30 100", text)  # the tab's size

    @unittest.skipIf(sys.platform == "win32", "no shell tab on Windows")
    def test_ultron_reads_the_screen(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/sh"}):
            with self.client.websocket_connect("/ws/terminal?n=3", headers={"origin": "http://127.0.0.1:8000"}) as ws:
                ws.send_text(json.dumps({"type": "screen", "text": "$ claude\n> hello"}))
                ws.send_text(json.dumps({"type": "input", "data": "echo ok\n"}))
                ws.receive_bytes()  # the screen message was handled before this input
                out = asyncio.run(read_terminal.handler({}))["content"][0]["text"]
                self.assertEqual(out, "Terminal 3:\n$ claude\n> hello")
        self.assertNotIn(3, terminal.SCREENS)  # gone with the tab

    def test_phone_is_refused(self):
        with self.assertRaises(WebSocketDisconnect) as e:
            with self.client.websocket_connect("/ws/terminal", headers={"origin": "https://mac.tail1234.ts.net"}) as ws:
                ws.receive_bytes()
        self.assertEqual(e.exception.code, 1008)

    def test_windows_says_no_shell(self):
        with mock.patch.object(terminal, "WINDOWS", True):
            with self.client.websocket_connect("/ws/terminal", headers={"origin": "http://127.0.0.1:8000"}) as ws:
                self.assertIn(b"isn't available on Windows", ws.receive_bytes())

    def test_loads_without_unix_modules(self):
        # Windows has no fcntl, pty or termios: importing terminal.py there must still work.
        code = ("import asyncio, subprocess, sys, config, fastapi; sys.platform = 'win32'; "
                "sys.modules.update(fcntl=None, pty=None, termios=None); import terminal")
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        done = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

if __name__ == "__main__":
    unittest.main()
