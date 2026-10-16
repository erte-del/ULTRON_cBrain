"""acc_read against a fake lap viewer on 127.0.0.1 (urllib doesn't care that the real one is https).
    .venv/bin/python -m unittest tests.test_acc
"""

import asyncio
import json
import re
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import config
from tools import acc, canvas, registry

SEEN: list[str] = []


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append(self.path)
        if self.path.startswith("/api/tool/compare_laps"):
            body = {"total_delta_s": 0.4, "biggest": [{"name": "Eau Rouge", "delta_s": 0.25}],
                    "lap_a": {"lap": 3}, "lap_b": {"lap": 2}}
        else:
            body = {"speed_kmh": 180}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def call(**args):
    result = asyncio.run(acc.acc_read.handler(args))
    return result["content"][0]["text"], bool(result.get("is_error"))


class AccTest(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port

    def test_label(self):
        self.assertEqual(registry.classify("mcp__ultron__acc_read"), "read")
        self.assertFalse(registry.needs_ok("mcp__ultron__acc_read", {"what": "get_live_state"}))

    def test_off_when_unset(self):
        with mock.patch.object(config, "ACC_URL", ""):
            text, err = call(what="get_live_state")
        self.assertTrue(err)
        self.assertIn("JARVIS_ACC_URL", text)

    def test_reads_and_compares(self):
        shown = []

        async def fake_table(title, columns, rows):
            shown.append(rows)
            return "c1"

        with mock.patch.object(config, "ACC_URL", f"http://127.0.0.1:{self.port}"), \
                mock.patch.object(canvas, "show_table", fake_table):
            text, err = call(what="get_live_state")
            self.assertFalse(err)
            self.assertEqual(json.loads(text)["speed_kmh"], 180)
            text, err = call(what="compare_laps", lap_a="last", lap_b="best")
            self.assertFalse(err)
        self.assertIn("/api/tool/compare_laps?lap_a=last&lap_b=best", SEEN)
        self.assertEqual(shown, [[["Eau Rouge", "+0.250 s"]]])

    def test_url_accepts_tailnet_port(self):
        ok = ["https://inancools.tail73572e.ts.net:8443", "https://pc.tail1234.ts.net"]
        bad = ["http://pc.tail1234.ts.net", "https://evil.example.com:8443", "https://pc.tail1234.ts.net:"]
        for url in ok:
            self.assertIsNotNone(re.fullmatch(config.ACC_URL_PATTERN, url), url)
        for url in bad:
            self.assertIsNone(re.fullmatch(config.ACC_URL_PATTERN, url), url)

    def test_unreachable(self):
        with mock.patch.object(config, "ACC_URL", "http://127.0.0.1:9"):
            text, err = call(what="get_session_info")
        self.assertTrue(err)
        self.assertIn("isn't reachable", text)


if __name__ == "__main__":
    unittest.main()
