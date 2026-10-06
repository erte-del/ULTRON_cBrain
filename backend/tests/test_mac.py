"""This Mac: labels, the folder fence, no overwrites, what may be opened, the Python sandbox.
Nothing is opened, copied or changed outside a temp folder.
    .venv/bin/python -m unittest tests.test_mac
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from tools import mac, maps, registry


def call(handler, **args):
    return asyncio.run(handler.handler(args))


class MacTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "Ultron"
        self.downloads = Path(tmp.name).resolve() / "Downloads"
        self.downloads.mkdir()
        for patch in [mock.patch.object(config, "FILES_DIR", self.root),
                      mock.patch.object(config, "ALLOWED_DIRS", [self.downloads])]:
            patch.start()
            self.addCleanup(patch.stop)
        self.calls = []

        async def fake_run(*cmd, **kw):
            self.calls.append(cmd)
            return 0, "", ""

        self.fake_run = fake_run

    def test_labels_and_no_card(self):
        self.assertEqual(registry.classify("mcp__ultron__mac_read"), "read")
        self.assertEqual(registry.classify("mcp__ultron__mac_change"), "act")
        self.assertEqual(registry.classify("mcp__ultron__run_python"), "act")
        self.assertFalse(registry.needs_ok("mcp__ultron__mac_change", {"action": "trash", "path": "a.txt"}))

    def test_paths_stay_in_the_allowed_folders(self):
        self.root.mkdir()
        (self.root.parent / "secret.txt").write_text("x")
        (self.root / "link").symlink_to(self.root.parent)
        (self.downloads / "out").symlink_to(self.root.parent)
        for bad in ["../secret.txt", str(self.root.parent / "secret.txt"), "~/.zshrc", "link/secret.txt",
                    str(self.downloads / "out/secret.txt"), str(config.ROOT_DIR / "backend/config.py")]:
            with self.assertRaises(ValueError, msg=bad):
                mac.allowed_path(bad)
        self.assertEqual(mac.allowed_path(str(self.root / "a.txt")), self.root / "a.txt")
        self.assertEqual(mac.allowed_path(str(self.downloads / "a.pdf")), self.downloads / "a.pdf")

    def test_changes_outside_ultrons_folder_ask_first(self):
        ok = lambda **args: registry.needs_ok("mcp__ultron__mac_change", args)
        self.assertFalse(ok(action="move", path="a.pdf", to="School/a.pdf"))
        self.assertTrue(ok(action="move", path=str(self.downloads / "a.pdf"), to="School"))
        self.assertTrue(ok(action="move", path="a.pdf", to=str(self.downloads)))
        self.assertTrue(ok(action="trash", path=str(self.downloads / "a.pdf")))
        self.assertFalse(ok(action="open_file", path=str(self.downloads / "a.pdf")))  # opening is free

    def test_moves_between_your_folders_and_finds_with_spotlight(self):
        self.root.mkdir()
        (self.downloads / "Chem notes.pdf").write_text("a")
        self.assertIn("Chem notes.pdf", mac.move(str(self.downloads / "Chem notes.pdf"), "School/Chem notes.pdf"))
        self.assertTrue((self.root / "School/Chem notes.pdf").exists())
        with self.assertRaises(ValueError):
            mac.move(str(self.downloads), "School")  # the folder itself stays put
        (self.downloads / "Chem lab.pdf").write_text("b")
        (self.downloads / "Maths.pdf").write_text("c")

        async def spotlight(*cmd, **kw):  # what mdfind would answer, plus a file it hasn't dropped yet
            self.calls.append(cmd)
            return 0, f"{self.downloads}/Chem lab.pdf\n{self.downloads}/Chem gone.pdf\n", ""
        with mock.patch.object(mac, "_run", spotlight):
            found = asyncio.run(mac.find_files('chem "pdf', "Downloads"))
        self.assertEqual([f["path"] for f in found], [str(self.downloads / "Chem lab.pdf")])
        self.assertIn('kMDItemFSName == "*chem*"cd || kMDItemFSName == "*pdf*"cd', self.calls[0])
        listed = asyncio.run(mac.find_files("", "all"))  # no query: the top of Downloads, all of Ultron's
        self.assertEqual({f["path"] for f in listed},
                         {"School/", "School/Chem notes.pdf", str(self.downloads / "Chem lab.pdf"),
                          str(self.downloads / "Maths.pdf")})

    def test_move_renames_into_folders_and_never_overwrites(self):
        self.root.mkdir()
        (self.root / "a.pdf").write_text("a")
        (self.root / "b.pdf").write_text("b")
        (self.root / "Invoices").mkdir()
        mac.move("a.pdf", "Invoices")
        self.assertTrue((self.root / "Invoices/a.pdf").exists())
        mac.move("Invoices/a.pdf", "2026/March/a.pdf")  # makes the folders
        self.assertTrue((self.root / "2026/March/a.pdf").exists())
        result = call(mac.mac_change, action="move", path="b.pdf", to="2026/March/a.pdf")
        self.assertTrue(result["is_error"])
        self.assertEqual((self.root / "2026/March/a.pdf").read_text(), "a")
        self.assertTrue(call(mac.mac_change, action="move", path="b.pdf", to="../b.pdf")["is_error"])

    def test_reads_whats_inside_files(self):
        import subprocess
        (self.downloads / "notes.txt").write_text("Le Chatelier shifts equilibrium")
        subprocess.run(["textutil", "-convert", "docx", str(self.downloads / "notes.txt")], check=True)
        import openpyxl
        book = openpyxl.Workbook()
        book.active.append(["Le Chatelier", None, 3])
        book.save(self.downloads / "notes.xlsx")
        (self.downloads / "app.bin").write_bytes(b"\0\1\2")
        read = lambda path: call(mac.mac_read, what="content", path=str(path))
        for name in ["notes.txt", "notes.docx", "notes.xlsx"]:
            self.assertIn("Le Chatelier", read(self.downloads / name)["content"][0]["text"], name)
        self.assertTrue(read(self.downloads / "app.bin")["is_error"])
        self.assertTrue(read(config.ROOT_DIR / ".env.example")["is_error"])  # Ultron's code is off limits
        self.assertFalse(registry.needs_ok("mcp__ultron__mac_read", {"what": "content", "path": "x"}))

    def test_only_documents_web_pages_and_real_apps_open(self):
        self.root.mkdir()
        (self.root / "run.command").write_text("echo hi")
        (self.root / "report.pdf").write_text("%PDF")
        with mock.patch.object(mac, "_run", self.fake_run):
            self.assertTrue(call(mac.mac_change, action="open_file", path="run.command")["is_error"])
            self.assertNotIn(("open", str(self.root / "run.command")), self.calls)  # only revealed in Finder
            call(mac.mac_change, action="open_file", path="report.pdf")
            self.assertIn(("open", str(self.root / "report.pdf")), self.calls)
            for url in ["file:///etc/passwd", "whatsapp://send?text=x", "javascript:alert(1)"]:
                self.assertTrue(call(mac.mac_change, action="open_url", url=url)["is_error"], url)
            self.assertTrue(call(mac.mac_change, action="open_app", name=str(self.root / "x.app"))["is_error"])
        self.assertEqual(mac.find_app("finder"), None)  # Finder lives in CoreServices, not Applications
        self.assertEqual(mac.find_app("Calculator"), Path("/System/Applications/Calculator.app"))

    def test_location(self):
        def fake_open(answer):
            async def run(*cmd, **kw):
                self.calls.append(cmd)
                Path(cmd[cmd.index("--stdout") + 1]).write_text(answer)
                return ""
            return run

        with mock.patch.object(mac, "LOCATION_APP", self.root):  # any folder that exists
            for answer, expect in [('{"latitude": 25.1, "longitude": 55.2, "place": "Dubai"}', "Dubai"),
                                   ('{"error": "denied"}', "Location Services")]:
                with mock.patch.object(mac, "_out", fake_open(answer)):
                    self.root.mkdir(exist_ok=True)
                    result = call(mac.mac_read, what="location")
                self.assertIn(expect, result["content"][0]["text"])
                self.assertEqual("is_error" in result, expect != "Dubai")
        with mock.patch.object(mac, "LOCATION_APP", self.root / "missing.app"):
            self.assertIn("setup_location.sh", call(mac.mac_read, what="location")["content"][0]["text"])

    def test_maps(self):
        self.assertEqual(registry.classify("mcp__ultron__maps"), "read")

        async def fake_run(*cmd, **kw):
            self.calls.append(cmd)
            Path(cmd[cmd.index("--stdout") + 1]).write_text('{"minutes": 20, "to": {"name": "Dubai Mall"}}')
            return 0, "", ""

        with mock.patch.object(mac, "LOCATION_APP", self.root), mock.patch.object(mac, "_run", fake_run):
            self.root.mkdir()
            result = call(maps.maps, action="directions", to="Dubai Mall", arrive_by="2026-10-02T09:00:00+04:00")
            self.assertIn('"minutes": 20', result["content"][0]["text"])
            args = self.calls[-1][self.calls[-1].index("--args") + 1:]
            self.assertEqual(args[0], "directions")
            self.assertEqual(json.loads(args[1]), {"to": "Dubai Mall", "arrive_by": "2026-10-02T09:00:00+04:00"})
            self.assertTrue(call(maps.maps, action="directions")["is_error"])  # no destination
            self.assertTrue(call(maps.maps, action="search", query="x", mode="flying")["is_error"])

    def test_map_card_only_frames_google_maps(self):
        from tools import canvas
        route = canvas.map_data({"from": "25.08,55.25", "to": "25.19,55.27", "mode": "walking", "view": "satellite"})
        self.assertEqual(route["url"], "https://www.google.com/maps?saddr=25.08%2C55.25&daddr=25.19%2C55.27&dirflg=w&t=k&output=embed")
        place = canvas.map_data({"place": "coffee near 25.08,55.25&output=x", "zoom": 14})
        self.assertTrue(place["url"].startswith(canvas.MAP_URL + "q=coffee+near+25.08%2C55.25%26output%3Dx&z=14"))
        with self.assertRaises(ValueError):
            canvas.map_data({})

    @unittest.skipUnless(Path("/usr/bin/sandbox-exec").exists(), "macOS only")
    def test_python_sandbox(self):
        self.root.mkdir()
        (self.root / "data.csv").write_text("a,b\n1,2\n3,4\n")
        outside = self.root.parent / "outside.txt"
        outside.write_text("secret")
        code = f"""
import csv, statistics, subprocess, urllib.request
print("mean", statistics.mean(int(r["b"]) for r in csv.DictReader(open("../data.csv"))))
open("result.txt", "w").write("ok")
for label, f in [("read", lambda: open({str(outside)!r}).read()), ("write", lambda: open("../x.txt", "w")),
                 ("net", lambda: urllib.request.urlopen("https://example.com", timeout=3)),
                 ("exec", lambda: subprocess.run(["/usr/bin/true"]))]:
    try:
        f(); print(label, "ALLOWED")
    except Exception:
        print(label, "blocked")
"""
        text = call(mac.run_python, code=code)["content"][0]["text"]
        self.assertIn("mean 3", text)
        self.assertNotIn("ALLOWED", text)
        self.assertEqual((self.root / "Output/result.txt").read_text(), "ok")
        self.assertFalse((self.root / "x.txt").exists())


if __name__ == "__main__":
    unittest.main()
