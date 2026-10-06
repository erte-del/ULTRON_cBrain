"""3D library tests. Run from the backend folder:
    .venv/bin/python -m unittest discover tests
"""

import asyncio
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import trimesh

import config
from storage import model_store
from tools import library3d, models3d, shapes
from tools import registry
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
        self.assertIn("mcp__3dassets__search_assets", text(result))

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
        self.assertIn("The parts are: 'model", text(small))  # the finished model is one part called 'model'
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


class AssetsDevTest(unittest.TestCase):
    """3DAssets.dev: allowed hosts, download, and the tool gate. (No real network.)"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = model_store.MODELS_DIR, library3d._download
        model_store.MODELS_DIR = Path(self.tmp.name)
        self.glb = trimesh.creation.box([0.5, 1.0, 0.25]).export(file_type="glb")
        self.fetched = []
        library3d._download = lambda url: self.fetched.append(url) or self.glb
        self.url = "https://3dassets.dev/cdn/models/tree.glb"

    def tearDown(self):
        model_store.MODELS_DIR, library3d._download = self.old
        self.tmp.cleanup()

    def test_shows_a_downloaded_model_as_a_finished_library_model(self):
        result = run(library3d.show_3d_asset, url=self.url, title="Tree")
        self.assertFalse(result.get("is_error"), result)
        self.assertEqual(self.fetched, [self.url])
        rec = model_store.load("mdl_001")
        self.assertEqual((rec.title, rec.versions[0].source, rec.versions[0].size), ("Tree", "library", [0.5, 1.0, 0.25]))
        self.assertIn("3DAssets.dev", text(result))
        self.assertEqual(model_store.file_path("mdl_001", "v1_preview.glb").read_bytes(), self.glb)

    def test_only_https_links_on_allowed_hosts(self):
        for url in ["http://3dassets.dev/a.glb", "https://evil.example/a.glb", "https://3dassets.dev.evil.example/a.glb",
                    "https://127.0.0.1/a.glb", "file:///etc/passwd", ""]:
            result = run(library3d.show_3d_asset, url=url, title="x")
            self.assertTrue(result.get("is_error"), url)
        self.assertEqual(self.fetched, [])
        self.assertFalse(Path(self.tmp.name, "mdl_001").exists())

    def test_cdn_subdomains_of_an_allowed_host_work(self):
        self.assertTrue(library3d._allowed_host("https://cdn.3dassets.dev/x.glb"))

    def test_real_download_refuses_redirects_and_big_files(self):
        library3d._download = self.old[1]  # the real one, against a local server
        small = library3d.MAX_ASSET_BYTES
        library3d.MAX_ASSET_BYTES = 100

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/ok":
                    self.send_response(200); self.end_headers(); self.wfile.write(b"x" * 50)
                elif self.path == "/big":
                    self.send_response(200); self.end_headers(); self.wfile.write(b"x" * 500)
                else:
                    self.send_response(302); self.send_header("Location", "http://example.com/"); self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(library3d._download(base + "/ok"), b"x" * 50)
            with self.assertRaises(ValueError):
                library3d._download(base + "/big")
            with self.assertRaises(Exception):  # the redirect is not followed
                library3d._download(base + "/moved")
        finally:
            server.shutdown()
            library3d.MAX_ASSET_BYTES = small

    def test_a_failed_download_is_explained(self):
        def boom(url):
            raise ValueError("bigger than 50 MB")
        library3d._download = boom
        result = run(library3d.show_3d_asset, url=self.url, title="Tree")
        self.assertTrue(result.get("is_error"))
        self.assertIn("preview_3d", text(result))

    def test_quantized_glb_gets_its_real_size(self):
        # how 3DAssets ships models: KHR_mesh_quantization, normalized int16 positions
        import struct
        pos = struct.pack("<9h", 32767, 0, 0, 0, 32767, 0, 0, 0, 0) + b"\0\0"
        gltf = {"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_mesh_quantization"],
                "extensionsRequired": ["KHR_mesh_quantization"], "scene": 0,
                "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                "buffers": [{"byteLength": len(pos)}], "bufferViews": [{"buffer": 0, "byteLength": 18}],
                "accessors": [{"bufferView": 0, "componentType": 5122, "normalized": True, "count": 3,
                               "type": "VEC3", "min": [0, 0, 0], "max": [32767, 32767, 0]}]}
        js = json.dumps(gltf).encode()
        js += b" " * (-len(js) % 4)
        body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(pos), b"BIN\0") + pos
        glb = struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body
        _, size = library3d._read_downloaded(glb)
        self.assertEqual(size[:2], [1.0, 1.0])

    def test_search_tools_run_freely_but_account_changes_ask(self):
        self.assertEqual(registry.classify("mcp__3dassets__search_assets"), "read")
        self.assertEqual(registry.classify("mcp__3dassets__get_asset"), "read")
        for name in ("create_account", "submit_asset_from_url", "update_asset", "get_upload_url"):
            self.assertEqual(registry.classify(f"mcp__3dassets__{name}"), "act", name)
        self.assertIn("mcp__3dassets__search_assets", registry.auto_allowed())
        self.assertNotIn("mcp__3dassets__create_account", registry.auto_allowed())
        self.assertEqual(registry.classify("mcp__ultron__show_3d_asset"), "read")

    def test_the_mcp_server_is_connected_unless_turned_off(self):
        self.assertEqual(registry.mcp_servers()["3dassets"], {"type": "http", "url": "https://3dassets.dev/mcp"})
        old = config.ASSETS_3D_MCP_URL
        config.ASSETS_3D_MCP_URL = ""
        try:
            self.assertNotIn("3dassets", registry.mcp_servers())
            self.assertFalse(any("3dassets" in n for n in registry.auto_allowed()))
        finally:
            config.ASSETS_3D_MCP_URL = old


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


def _house_glb(materials=("plaster", "thatch")):
    """A 'house' like 3DAssets ships them: meshes with named materials, sitting off-center."""
    scene = trimesh.Scene()
    for k, name in enumerate(materials):
        box = trimesh.creation.box([2.0, 1.0, 2.0])
        box.apply_translation([5.0, 0.5 + k, 3.0])
        box.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(name=name, baseColorFactor=[200, 200, 200, 255]))
        scene.add_geometry(box, node_name=name, geom_name=name)
    return scene.export(file_type="glb")


class EditAssetTest(unittest.TestCase):
    """Recolor and combine models pulled from 3DAssets.dev."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = model_store.MODELS_DIR, library3d._download
        model_store.MODELS_DIR = Path(self.tmp.name)
        garden = trimesh.creation.box([10.0, 0.1, 10.0])
        garden.apply_translation([0, 0.05, 0])
        self.files = {"house": _house_glb(), "garden": garden.export(file_type="glb")}
        library3d._download = lambda url: self.files[url.rsplit("/", 1)[1]]

    def tearDown(self):
        model_store.MODELS_DIR, library3d._download = self.old
        self.tmp.cleanup()

    def show(self, name):
        result = run(library3d.show_3d_asset, url=f"https://cdn.3dassets.dev/m/{name}", title=name)
        self.assertFalse(result.get("is_error"), result)
        return text(result)

    def colors(self, model_id):
        glb = model_store.file_path(model_id, f"v{model_store.load(model_id).current}_preview.glb").read_bytes()
        return {shapes._material_name(g): tuple(g.visual.material.baseColorFactor[:3])
                for g in shapes.load_glb(glb).geometry.values() if hasattr(g.visual, "material")}

    def test_recolors_a_finished_model_by_material(self):
        self.assertIn("plaster, thatch", self.show("house"))
        result = run(models3d.preview_3d, model_id="mdl_001",
                     update_parts=[{"name": "model", "colors": {"plaster": "blue"}}])
        self.assertFalse(result.get("is_error"), result)
        colors = self.colors("mdl_001")
        self.assertEqual(colors["plaster"], (0, 0, 255))
        self.assertEqual(colors["thatch"], (200, 200, 200))
        rec = model_store.load("mdl_001")
        self.assertEqual(model_store.spec(rec)["parts"][0]["version"], 1)  # pinned to the original

    def test_unknown_material_lists_the_real_ones(self):
        self.show("house")
        result = run(models3d.preview_3d, model_id="mdl_001",
                     update_parts=[{"name": "model", "colors": {"walls": "blue"}}])
        self.assertTrue(result.get("is_error"))
        self.assertIn("plaster, thatch", text(result))

    def test_combines_two_models_and_keeps_them_editable(self):
        self.show("house")
        self.show("garden")
        spec = {"parts": [{"name": "garden", "shape": "asset", "model": "mdl_002"},
                          {"name": "house", "shape": "asset", "model": "mdl_001", "position": [0, 0.1, 0]}]}
        result = run(models3d.preview_3d, title="House with garden", spec=spec)
        self.assertFalse(result.get("is_error"), result)
        self.assertNotIn("PROBLEM", text(result))  # house sits on the lawn; its own meshes count as one part
        rec = model_store.load("mdl_003")
        self.assertEqual(rec.versions[0].size, [10.0, 2.1, 10.0])  # house re-centered onto the garden
        change = run(models3d.preview_3d, model_id="mdl_003",
                     update_parts=[{"name": "house", "colors": {"plaster": "#0000ff"}}])
        self.assertFalse(change.get("is_error"), change)
        self.assertEqual(self.colors("mdl_003")["plaster"], (0, 0, 255))

    def test_a_missing_model_is_a_clear_error(self):
        result = run(models3d.preview_3d, spec={"parts": [{"name": "x", "shape": "asset", "model": "mdl_999"}]})
        self.assertTrue(result.get("is_error"))
        self.assertIn("existing model id", text(result))
