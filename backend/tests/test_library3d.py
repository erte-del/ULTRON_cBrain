"""3D library tests. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import trimesh

import config
from storage import model_store
from tools import library3d, models3d, shapes
from tools.registry import TOOLS

from test_models3d import CHAIR


def run(tool, **args):
    return asyncio.run(tool.handler(args))


def text(result):
    return result["content"][0]["text"]


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.lib, models = root / "lib", root / "models"
        self.lib.mkdir()
        self.old = config.LIBRARY_3D_DIR, model_store.MODELS_DIR
        config.LIBRARY_3D_DIR, model_store.MODELS_DIR = self.lib, models

        (self.lib / "chair.json").write_text(json.dumps(
            {"title": "Wooden chair", "aliases": ["dining chair"], "tags": ["seat"], "spec": CHAIR}))
        box = trimesh.creation.box([0.4, 0.2, 0.6])
        (self.lib / "toy-truck.glb").write_bytes(box.export(file_type="glb"))
        (self.lib / "toy-truck.json").write_text(json.dumps({"title": "Toy truck", "aliases": ["lorry"]}))
        (self.lib / "plain-bench.glb").write_bytes(box.export(file_type="glb"))  # no sidecar at all

    def tearDown(self):
        config.LIBRARY_3D_DIR, model_store.MODELS_DIR = self.old
        self.tmp.cleanup()

    def test_finds_models_by_name_alias_and_plural(self):
        for query, found in [("chair", "chair"), ("a dining chair please", "chair"), ("chairs", "chair"),
                             ("show me the lorry", "toy-truck"), ("plain bench", "plain-bench")]:
            hits = library3d.search(query)
            self.assertEqual([(i.id, q) for i, q in hits[:1]], [(found, "exact")], query)

    def test_a_different_object_is_not_in_the_library(self):
        self.assertEqual(library3d.search("porsche 911"), [])
        result = run(library3d.search_3d_library, query="porsche 911")
        self.assertIn("Nothing in the 3D library", text(result))
        self.assertIn("preview_3d", text(result))

    def test_only_close_is_not_an_exact_match(self):
        # asked for an office chair: the library only has "chair", which may not be what they mean
        hits = library3d.search("office chair")
        self.assertEqual([(i.id, q) for i, q in hits], [("chair", "partial")])
        self.assertIn("Nothing in the 3D library", text(run(library3d.search_3d_library, query="office chair")))

    def test_empty_query_lists_everything(self):
        listing = text(run(library3d.search_3d_library))
        for name in ("chair", "toy-truck", "plain-bench"):
            self.assertIn(name, listing)

    def test_broken_files_are_skipped(self):
        (self.lib / "broken.json").write_text("{not json")
        (self.lib / "no-spec.json").write_text("{}")  # nothing to show
        (self.lib / "Bad Name.glb").write_bytes(b"x")
        self.assertEqual(sorted(i.id for i in library3d.items()), ["chair", "plain-bench", "toy-truck"])

    def test_showing_a_spec_model_keeps_it_editable(self):
        result = run(library3d.show_from_3d_library, item_id="chair")
        self.assertFalse(result.get("is_error"), result)
        rec = model_store.load("mdl_001")
        self.assertEqual(rec.title, "Wooden chair")
        self.assertEqual(rec.versions[0].source, "")  # shown like a normal preview
        self.assertEqual(model_store.spec(rec), CHAIR)
        change = run(models3d.preview_3d, model_id="mdl_001", update_parts=[{"name": "seat", "color": "red"}])
        self.assertFalse(change.get("is_error"), change)
        self.assertEqual(model_store.load("mdl_001").current, 2)

    def test_showing_a_glb_model_shows_the_file_itself(self):
        result = run(library3d.show_from_3d_library, item_id="toy-truck")
        self.assertFalse(result.get("is_error"), result)
        rec = model_store.load("mdl_001")
        self.assertEqual(rec.versions[0].source, "library")
        self.assertEqual(rec.versions[0].size, [0.4, 0.2, 0.6])
        self.assertEqual(model_store.file_path("mdl_001", "v1_preview.glb").read_bytes(),
                         (self.lib / "toy-truck.glb").read_bytes())
        self.assertEqual(model_store.card_data(rec)["versions"][0]["source"], "library")
        self.assertIn("rebuild", text(result))

    def test_changing_a_glb_model_means_a_full_rebuild(self):
        run(library3d.show_from_3d_library, item_id="toy-truck")
        small = run(models3d.preview_3d, model_id="mdl_001", update_parts=[{"name": "x", "color": "red"}])
        self.assertTrue(small.get("is_error"))
        self.assertIn("full 'spec'", text(small))
        rebuilt = run(models3d.preview_3d, model_id="mdl_001", spec=CHAIR, note="rebuilt")
        self.assertFalse(rebuilt.get("is_error"), rebuilt)
        self.assertEqual(model_store.load("mdl_001").current, 2)
        self.assertEqual(model_store.load("mdl_001").versions[1].source, "")

    def test_unknown_item_is_an_error(self):
        for item_id in ("nope", "../chair", ""):
            self.assertTrue(run(library3d.show_from_3d_library, item_id=item_id).get("is_error"), item_id)

    def test_tools_are_registered_as_read(self):
        kinds = {t.tool.name: t.kind for t in TOOLS}
        self.assertEqual(kinds["search_3d_library"], "read")
        self.assertEqual(kinds["show_from_3d_library"], "read")


class SeedLibraryTest(unittest.TestCase):
    """The models shipped in backend/library3d must all build, and hold together."""

    def test_every_shipped_model_builds_without_floating_parts(self):
        shipped = library3d.items()
        self.assertGreaterEqual(len(shipped), 4)
        for item in shipped:
            with self.subTest(item=item.id):
                scene = shapes.build_scene(shapes.validate(item.spec), "preview")
                self.assertEqual(shapes.floating_parts(scene), [])


if __name__ == "__main__":
    unittest.main()
