"""Which device you're talking from reaches Ultron, so "play this" happens on that device.
Run from the backend folder:
    .venv/bin/python -m unittest tests.test_device
"""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

import main
from brain.agent import Ultron
from brain.base import Done
from tools import mac, phone

PHONE_UA = "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0 Mobile Safari/537.36"
MAC_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"


def tab(origin: str, ua: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"origin": origin, "user-agent": ua})


class DeviceTest(unittest.IsolatedAsyncioTestCase):
    def test_device_of(self):
        self.assertEqual(main.device_of(tab("http://127.0.0.1:8000", MAC_UA)), "this Mac")
        self.assertEqual(main.device_of(tab("https://mac.tail1234.ts.net", PHONE_UA)), "the user's Android phone")
        self.assertEqual(main.device_of(tab("https://mac.tail1234.ts.net", MAC_UA)), "another computer, not this Mac")

    async def test_note_reaches_the_brain(self):
        sent: list[str] = []

        class Brain:
            provider, model, context_tokens, last_active = "claude", "sonnet", 0, 0.0

            async def send(self, text, images=None, model="sonnet"):
                sent.append(text)
                yield Done("claude-sonnet-5")

        async for _ in Ultron(Brain()).handle_text("play some music", device="the user's Android phone"):
            pass
        self.assertTrue(sent[0].startswith("[Device: the user's Android phone]\n[Now: "))

    def test_phone_location(self):
        self.assertEqual(main.phone_location([25.2, 55.3]), [25.2, 55.3])
        for bad in (None, "12", [1], [91, 0], [0, "x"], {"lat": 1}):
            self.assertIsNone(main.phone_location(bad))

    def test_phone_status(self):
        self.assertEqual(main.phone_status({"battery": 0.824, "charging": True, "network": "cellular", "dark": False}),
                         "Battery: 82%, charging\nNetwork: mobile data\nAppearance: light")
        self.assertEqual(main.phone_status({"dark": True, "battery": 7, "network": "<b>"}), "Appearance: dark")
        for bad in (None, "x", {}, [1]):
            self.assertIsNone(main.phone_status(bad))

    async def test_status_shows_the_phone_first(self):
        async def mac_status():
            return "Battery: 50%"

        with mock.patch.object(mac, "_status", mac_status):
            mac.phone_status = "Battery: 82%, charging"
            try:
                out = (await mac.mac_read.handler({"what": "status"}))["content"][0]["text"]
            finally:
                mac.phone_status = None
            self.assertTrue(out.startswith("The device the user is on (phone or PC browser):\nBattery: 82%, charging"))
            self.assertIn("This Mac:\nBattery: 50%", out)
            on_mac = (await mac.mac_read.handler({"what": "status"}))["content"][0]["text"]
        self.assertEqual(on_mac, "Battery: 50%")

    async def test_phone_volume(self):
        called: list[str] = []
        url = "https://trigger.macrodroid.com/abc-123/jarvis_volume"
        with mock.patch.object(phone.config, "MACRODROID_WEBHOOK", url), mock.patch.object(phone, "_call", called.append):
            out = await phone.phone_volume.handler({"volume": 140})
            await phone.phone_volume.handler({"volume": "x"})
        self.assertNotIn("is_error", out)
        self.assertEqual(called, ["https://trigger.macrodroid.com/abc-123/jarvis_volume?volume_level=100"])
        with mock.patch.object(phone.config, "MACRODROID_WEBHOOK", ""):
            self.assertTrue((await phone.phone_volume.handler({"volume": 5}))["is_error"])

    async def test_phone_taxi(self):
        called: list[str] = []
        url = "https://trigger.macrodroid.com/abc-123/jarvis_volume"
        with mock.patch.object(phone.config, "MACRODROID_WEBHOOK", url), mock.patch.object(phone, "_call", called.append):
            out = await phone.phone_taxi.handler({"destination": "  Dubai   Mall & Co "})
            await phone.phone_taxi.handler({})
        self.assertNotIn("is_error", out)
        self.assertEqual(called, ["https://trigger.macrodroid.com/abc-123/jarvis_careem?taxi_to=Dubai+Mall+%26+Co",
                                  "https://trigger.macrodroid.com/abc-123/jarvis_careem?taxi_to="])

    async def test_locator_starts_from_the_phone(self):
        args: list[tuple] = []

        async def fake_out(*cmd, **kw):
            args.append(cmd)
            return ""

        with mock.patch.object(mac, "_out", fake_out), mock.patch.object(mac, "LOCATION_APP", mock.Mock(exists=lambda: True)), \
                mock.patch.object(mac.Path, "read_text", return_value='{"place": "x"}'):
            mac.phone_here = [25.2, 55.3]
            try:
                await mac.locator("search", {"query": "coffee"})
            finally:
                mac.phone_here = None
            await mac.locator()
        self.assertEqual(json.loads(args[0][-1]), {"query": "coffee", "here": [25.2, 55.3]})
        self.assertEqual(json.loads(args[1][-1]), {})  # on the Mac: its own GPS


if __name__ == "__main__":
    unittest.main()
