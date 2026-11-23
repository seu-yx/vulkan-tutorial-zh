import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("translation_cache_module", Path(__file__).parents[1] / "scripts/translation_cache.py")
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class TranslationCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="translation-cache-")
        self.root = Path(self.temporary.name)
        self.path = self.root / "translations/google.jsonl"
        self.database = self.make_database()

    def tearDown(self):
        self.database.close()
        self.temporary.cleanup()

    def make_database(self):
        database = sqlite3.connect(":memory:")
        database.execute("CREATE TABLE translations (key TEXT PRIMARY KEY, source TEXT NOT NULL, html TEXT NOT NULL, translated_at TEXT NOT NULL)")
        return database

    def record(self, key="a" * 64, **changes):
        value = {"key": key, "source": "Select a physical device.", "html": "选择一个物理设备。", "translated_at": "2026-11-23T06:00:00+00:00"}
        value.update(changes)
        return value

    def insert(self, record):
        self.database.execute("INSERT INTO translations VALUES (?,?,?,?)", tuple(record[field] for field in ("key", "source", "html", "translated_at")))
        self.database.commit()

    def write_records(self, records, metadata=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        values = [cache.METADATA if metadata is None else metadata, *records]
        self.path.write_text("\n".join(json.dumps(value, ensure_ascii=False) for value in values) + "\n", encoding="utf-8")

    def test_export_import_roundtrip_and_stable_output(self):
        first = self.record("a" * 64)
        second = self.record("b" * 64, source="Record commands.", html="记录命令。")
        self.insert(second)
        self.insert(first)
        self.assertEqual(cache.export_cache(self.database, self.path, {second["key"], first["key"]}, self.root), 2)
        contents = self.path.read_bytes()
        modified = self.path.stat().st_mtime_ns
        self.assertEqual(cache.export_cache(self.database, self.path, {first["key"], second["key"]}, self.root), 2)
        self.assertEqual(self.path.read_bytes(), contents)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)
        self.assertEqual([json.loads(line)["key"] for line in contents.decode().splitlines()[1:]], [first["key"], second["key"]])
        restored = self.make_database()
        try:
            self.assertEqual(cache.import_cache(restored, self.path, self.root), 2)
            self.assertEqual(restored.execute("SELECT * FROM translations ORDER BY key").fetchall(), self.database.execute("SELECT * FROM translations ORDER BY key").fetchall())
        finally:
            restored.close()

    def test_export_excludes_legacy_edge_and_inactive_google_keys(self):
        legacy_edge_key = hashlib.sha256(json.dumps({"version": 4, "glossary": "terms", "text": "Select a device.", "tokens": {}}, sort_keys=True).encode()).hexdigest()
        active_google_key = hashlib.sha256(json.dumps({"version": 5, "provider": "google", "glossary": "terms", "text": "Select a device.", "tokens": {}}, sort_keys=True).encode()).hexdigest()
        self.insert(self.record(legacy_edge_key, html="Legacy Edge output"))
        self.insert(self.record("c" * 64, html="Inactive Google output"))
        self.insert(self.record(active_google_key))
        self.assertEqual(cache.export_cache(self.database, self.path, {active_google_key}, self.root), 1)
        lines = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(lines[0], cache.METADATA)
        self.assertEqual([record["key"] for record in lines[1:]], [active_google_key])

    def test_import_keeps_newer_local_rows_and_unlisted_entries(self):
        self.insert(self.record(html="更新的本地译文", translated_at="2026-11-24T06:00:00+00:00"))
        self.insert(self.record("b" * 64, source="An unlisted source.", html="未列入文件的译文"))
        self.write_records([self.record()])
        self.assertEqual(cache.import_cache(self.database, self.path, self.root), 0)
        self.assertEqual(self.database.execute("SELECT html FROM translations WHERE key=?", ("a" * 64,)).fetchone()[0], "更新的本地译文")
        self.assertEqual(self.database.execute("SELECT count(*) FROM translations").fetchone()[0], 2)
        self.write_records([self.record(html="较新的审阅译文", translated_at="2026-11-25T06:00:00+00:00")])
        self.assertEqual(cache.import_cache(self.database, self.path, self.root), 1)

    def test_malformed_import_is_atomic_and_rejects_wrong_provider(self):
        self.write_records([self.record()], metadata={**cache.METADATA, "provider": "edge"})
        with self.assertRaises(ValueError): cache.import_cache(self.database, self.path, self.root)
        self.write_records([self.record(), self.record("bad-sha256")])
        with self.assertRaises(ValueError): cache.import_cache(self.database, self.path, self.root)
        self.assertEqual(self.database.execute("SELECT count(*) FROM translations").fetchone()[0], 0)
        self.write_records([self.record(), self.record()])
        with self.assertRaises(ValueError): cache.import_cache(self.database, self.path, self.root)
        self.write_records([self.record(translated_at="2026-11-23T06:00:00")])
        with self.assertRaises(ValueError): cache.import_cache(self.database, self.path, self.root)

    def test_source_conflict_rolls_back_entire_merge(self):
        self.insert(self.record("b" * 64))
        self.write_records([self.record(), self.record("b" * 64, source="A different source.", translated_at="2026-11-25T06:00:00+00:00")])
        with self.assertRaises(ValueError): cache.import_cache(self.database, self.path, self.root)
        self.assertEqual(self.database.execute("SELECT count(*) FROM translations").fetchone()[0], 1)

    def test_paths_cannot_escape_project_or_overwrite_key_file(self):
        with self.assertRaises(ValueError): cache.cache_path("../outside.jsonl", self.root)
        with self.assertRaises(ValueError): cache.cache_path("proxy-key.pem", self.root)
        with self.assertRaises(ValueError): cache.cache_path(".git/google.jsonl", self.root)
        with self.assertRaises(FileNotFoundError): cache.import_cache(self.database, self.path, self.root)


if __name__ == "__main__":
    unittest.main()
