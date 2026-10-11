"""Obsidian notes: search, read, write, #private and the vault boundary.
    .venv/bin/python -m unittest tests.test_notes
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from tools import notes, registry


def call(tool, args):
    result = asyncio.run(tool.handler(args))
    return result["content"][0]["text"], result.get("is_error", False)


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        patch = mock.patch.object(config, "VAULT_DIR", self.vault)
        patch.start()
        self.addCleanup(patch.stop)
        (self.vault / "school").mkdir()
        (self.vault / "school" / "Chemistry.md").write_text("Test on acids and bases, Friday.")
        (self.vault / "Keys.md").write_text("my passphrase is hunter2 #private")
        (self.vault / "Tagged.md").write_text("---\ntags:\n  - private\n---\nchemistry secrets")
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "chemistry.md").write_text("chemistry config")

    def test_search_finds_notes_but_never_private_or_hidden_ones(self):
        text, _ = call(notes.search_notes, {"query": "chemistry"})
        self.assertIn("school/Chemistry.md", text)
        self.assertNotIn("Tagged", text)
        self.assertNotIn(".obsidian", text)
        self.assertNotIn("hunter2", call(notes.search_notes, {"query": ""})[0])

    def test_read(self):
        text, err = call(notes.read_note, {"path": "school/Chemistry"})
        self.assertFalse(err)
        self.assertIn("acids and bases", text)
        text, err = call(notes.read_note, {"path": "Keys.md"})
        self.assertTrue(err)
        self.assertNotIn("hunter2", text)

    def test_paths_stay_inside_the_vault(self):
        for path in ("../outside.md", "school/../../outside", ".obsidian/chemistry.md"):
            self.assertTrue(call(notes.read_note, {"path": path})[1], path)
            self.assertTrue(call(notes.write_note, {"path": path, "content": "x", "mode": "create"})[1], path)
        self.assertFalse((self.vault.parent / "outside.md").exists())
        # a leading slash still means "in the vault"
        call(notes.write_note, {"path": "/etc/passwd", "content": "x", "mode": "create"})
        self.assertTrue((self.vault / "etc" / "passwd.md").exists())

    def test_write_modes(self):
        self.assertFalse(call(notes.write_note, {"path": "Ultron/Plan", "content": "one", "mode": "create"})[1])
        self.assertTrue(call(notes.write_note, {"path": "Ultron/Plan.md", "content": "two", "mode": "create"})[1])
        call(notes.write_note, {"path": "Ultron/Plan.md", "content": "two", "mode": "append"})
        self.assertEqual((self.vault / "Ultron" / "Plan.md").read_text(), "one\ntwo\n")
        call(notes.write_note, {"path": "Ultron/Plan.md", "content": "three", "mode": "replace"})
        self.assertEqual((self.vault / "Ultron" / "Plan.md").read_text(), "three\n")
        # private notes are never changed
        self.assertTrue(call(notes.write_note, {"path": "Keys.md", "content": "x", "mode": "replace"})[1])
        self.assertIn("hunter2", (self.vault / "Keys.md").read_text())

    def test_reading_is_free_and_writing_asks_first(self):
        self.assertEqual(registry.classify(registry.PREFIX + "search_notes"), "read")
        self.assertEqual(registry.classify(registry.PREFIX + "read_note"), "read")
        self.assertEqual(registry.classify(registry.PREFIX + "write_note"), "act")

    def test_delete_asks_and_moves_to_trash(self):
        self.assertTrue(registry.needs_ok(registry.PREFIX + "delete_note", {"path": "school/Chemistry.md"}))
        self.assertFalse(call(notes.delete_note, {"path": "school/Chemistry"})[1])
        self.assertFalse((self.vault / "school" / "Chemistry.md").exists())
        self.assertTrue((self.vault / ".trash" / "Chemistry.md").exists())
        (self.vault / "school" / "A.md").write_text("a")
        self.assertFalse(call(notes.delete_note, {"path": "school"})[1])  # a folder
        self.assertFalse((self.vault / "school").exists())
        for path in ("Keys.md", "../x", ".obsidian", "", "missing"):  # private, outside, hidden, root, absent
            self.assertTrue(call(notes.delete_note, {"path": path})[1], path)
        self.assertTrue((self.vault / "Keys.md").exists())

    def test_no_vault_set(self):
        with mock.patch.object(config, "VAULT_DIR", None):
            text, err = call(notes.search_notes, {"query": "x"})
        self.assertTrue(err)
        self.assertIn("JARVIS_VAULT", text)


if __name__ == "__main__":
    unittest.main()
