"""Check the portable entry point without downloading or translating anything."""
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen


spec = importlib.util.spec_from_file_location("mirror_local", Path(__file__).parents[1] / "scripts/local.py")
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class LocalEntryTests(unittest.TestCase):
    def test_preview_does_not_need_build_dependencies(self):
        with patch.object(local, "serve") as serve, patch.object(local, "require_tools") as dependencies:
            self.assertEqual(local.main([]), 0)
        serve.assert_called_once_with(8080)
        dependencies.assert_not_called()

    def test_missing_or_empty_generated_catalog_explains_how_to_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            public = Path(temporary)
            with self.assertRaisesRegex(local.LocalError, r"local.py --setup --serve"):
                local.validate_site(public)
            (public / "index.html").write_text("Preview", encoding="utf-8")
            (public / "data").mkdir()
            (public / "data/catalog.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
            with self.assertRaisesRegex(local.LocalError, r"local.py --sync --serve"):
                local.validate_site(public)

    def test_local_build_imports_cache_without_starting_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interpreter = root / "python-placeholder"
            interpreter.touch()
            dependency = root / "node_modules/@asciidoctor/core/package.json"
            dependency.parent.mkdir(parents=True)
            dependency.write_text("{}", encoding="utf-8")
            cache = root / "translations/google.jsonl"
            cache.parent.mkdir()
            cache.write_text("{}\n", encoding="utf-8")
            with patch.object(local, "ROOT", root), patch.object(local, "virtual_python", return_value=interpreter), patch.object(local, "run") as run:
                local.build_site(cache, no_fetch=True)
            command = run.call_args.args[0]
            self.assertIn("--skip-translate", command)
            self.assertIn("--no-fetch", command)
            self.assertEqual(command[command.index("--import-cache") + 1], cache)

    def test_preview_serves_public_directory_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "public"
            public.mkdir()
            (public / "index.html").write_text("PUBLIC_SENTINEL", encoding="utf-8")
            (root / "outside.txt").write_text("PRIVATE_SENTINEL", encoding="utf-8")
            handler = local.partial(local.SimpleHTTPRequestHandler, directory=str(public))
            with local.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    address = f"http://127.0.0.1:{server.server_port}"
                    with urlopen(address + "/", timeout=5) as response:
                        self.assertEqual(response.read(), b"PUBLIC_SENTINEL")
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(address + "/../outside.txt", timeout=5)
                    self.assertEqual(failure.exception.code, 404)
                finally:
                    server.shutdown()
                    worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
