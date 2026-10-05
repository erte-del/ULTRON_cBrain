"""Uploads: the /upload endpoint and read_upload. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

import main
from storage import image_store, upload_store
from tools.uploads import read_upload

ORIGIN = {"origin": "http://127.0.0.1:5173"}


class UploadTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        for patch in (
            mock.patch.object(upload_store, "UPLOADS_DIR", tmp / "uploads"),
            mock.patch.object(image_store, "ASSETS_DIR", tmp / "assets"),
            mock.patch.object(main.hub, "emit", mock.AsyncMock()),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(main.app)  # no `with`: don't start Claude Code

    def post(self, name, data, headers=ORIGIN):
        return self.client.post("/upload", params={"name": name}, content=data, headers=headers)

    def read(self, file_id):
        return asyncio.run(read_upload.handler({"id": file_id}))

    def test_text_file_is_stored_and_readable(self):
        res = self.post("../../notes.txt", b"buy milk")
        self.assertEqual(res.status_code, 200)
        file_id = res.json()["id"]
        self.assertRegex(file_id, r"^upl_\d{3}$")
        self.assertEqual(upload_store.find(file_id).name, "notes.txt")  # no path tricks
        self.assertIn("buy milk", self.read(file_id)["content"][0]["text"])
        self.assertEqual(upload_store.label(file_id), f"{file_id} (notes.txt)")

    def test_image_goes_on_the_canvas(self):
        buf = io.BytesIO()
        Image.new("RGB", (40, 20), "red").save(buf, "PNG")
        file_id = self.post("photo.png", buf.getvalue()).json()["id"]
        self.assertRegex(file_id, r"^img_\d{3}$")
        main.hub.emit.assert_awaited_once()
        self.assertEqual(self.read(file_id)["content"][1]["type"], "image")

    def test_binary_file_is_refused_politely(self):
        file_id = self.post("app.bin", b"\0\1\2").json()["id"]
        self.assertTrue(self.read(file_id)["is_error"])

    def test_other_websites_cannot_upload(self):
        self.assertEqual(self.post("x.txt", b"hi", {"origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.post("x.txt", b"", ORIGIN).status_code, 400)

    def shot(self, color="blue", size=(2400, 1200)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, "JPEG")
        return self.client.post("/screen", content=buf.getvalue(), headers=ORIGIN)

    def test_screen_capture_stays_off_the_canvas_and_is_shrunk(self):
        res = self.shot()
        self.assertEqual(res.status_code, 200)
        file_id = res.json()["id"]
        self.assertRegex(file_id, r"^upl_\d{3}$")
        main.hub.emit.assert_not_awaited()
        content = self.read(file_id)["content"]
        self.assertIn("screen", content[0]["text"])
        self.assertEqual(content[1]["type"], "image")
        import base64
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(content[1]["data"]))).width, 1600)

    def test_only_the_newest_screen_captures_are_kept(self):
        ids = [self.shot(size=(40, 20)).json()["id"] for _ in range(upload_store.KEEP_SCREENS + 2)]
        for old in ids[:2]:
            with self.assertRaises(KeyError):
                upload_store.find(old)
        upload_store.find(ids[-1])

    def test_screen_endpoint_rejects_strangers_and_non_images(self):
        self.assertEqual(self.client.post("/screen", content=b"x", headers={"origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/screen", content=b"not an image", headers=ORIGIN).status_code, 400)
        self.assertEqual(self.client.post("/screen", content=b"", headers=ORIGIN).status_code, 400)


if __name__ == "__main__":
    unittest.main()
