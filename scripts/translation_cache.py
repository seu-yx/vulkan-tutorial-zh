"""Reviewable, deterministic Google v5 translation-cache interchange."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

METADATA = {
    "type": "metadata",
    "format": "vulkan-tutorial-translation-cache",
    "schema_version": 1,
    "provider": "google",
    "cache_key_version": 5,
}
FIELDS = {"key", "source", "html", "translated_at"}
KEY_PATTERN = re.compile(r"[0-9a-f]{64}")


def cache_path(path, workspace_root):
    """Keep explicitly requested cache files inside this checkout and away from Git internals."""
    root = Path(workspace_root).resolve()
    supplied = Path(path)
    supplied = supplied if supplied.is_absolute() else root / supplied
    if supplied.is_symlink(): raise ValueError("Translation cache must not be a symlink")
    resolved = supplied.resolve()
    if not resolved.is_relative_to(root): raise ValueError("Translation cache must be inside the project")
    relative = resolved.relative_to(root)
    if resolved.suffix.lower() != ".jsonl" or any(part in {".git", "node_modules"} for part in relative.parts):
        raise ValueError("Translation cache must be a project .jsonl file outside Git and dependency internals")
    if resolved.exists() and not resolved.is_file(): raise ValueError("Translation cache path is not a file")
    return resolved


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Duplicate JSON object field")
        result[key] = value
    return result


def _timestamp(value):
    if not isinstance(value, str): raise ValueError("Translation timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("Translation timestamp must include a timezone")
    return parsed


def _validate_record(record, line_number):
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise ValueError(f"Invalid translation record fields at line {line_number}")
    if not isinstance(record["key"], str) or not KEY_PATTERN.fullmatch(record["key"]):
        raise ValueError(f"Invalid SHA-256 translation key at line {line_number}")
    if not all(isinstance(record[field], str) and record[field].strip() for field in ("source", "html")):
        raise ValueError(f"Empty or invalid translation text at line {line_number}")
    try: _timestamp(record["translated_at"])
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid translation timestamp at line {line_number}") from error
    return record


def import_cache(database: sqlite3.Connection, path, workspace_root):
    """Validate the entire Google file, then merge atomically without replacing newer local rows."""
    path = cache_path(path, workspace_root)
    records = []
    seen = set()
    has_metadata = False
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try: record = json.loads(line, object_pairs_hook=_strict_object)
            except (json.JSONDecodeError, ValueError) as error:
                raise ValueError(f"Invalid translation cache JSON at line {number}") from error
            if number == 1:
                if record != METADATA or type(record.get("schema_version")) is not int or type(record.get("cache_key_version")) is not int:
                    raise ValueError("Translation cache metadata must identify Google cache key v5 and schema v1")
                has_metadata = True
                continue
            record = _validate_record(record, number)
            if record["key"] in seen: raise ValueError(f"Duplicate translation key at line {number}")
            seen.add(record["key"])
            records.append(record)
    if not has_metadata:
        raise ValueError("Translation cache is empty; the Google metadata line is required")
    changed = 0
    with database:
        for record in records:
            existing = database.execute("SELECT source, translated_at FROM translations WHERE key = ?", (record["key"],)).fetchone()
            if existing is not None:
                if existing[0] != record["source"]: raise ValueError("Translation key conflicts with a different source")
                if _timestamp(existing[1]) >= _timestamp(record["translated_at"]): continue
            database.execute("INSERT OR REPLACE INTO translations (key,source,html,translated_at) VALUES (?,?,?,?)",
                             (record["key"], record["source"], record["html"], record["translated_at"]))
            changed += 1
    return changed


def export_cache(database: sqlite3.Connection, path, active_google_keys, workspace_root):
    """Export only keys computed for the current Google v5 source corpus, never legacy DB rows."""
    path = cache_path(path, workspace_root)
    keys = set(active_google_keys)
    if any(not isinstance(key, str) or not KEY_PATTERN.fullmatch(key) for key in keys):
        raise ValueError("Active Google cache keys must be SHA-256 strings")
    rows = []
    for key, source, translated_html, translated_at in database.execute("SELECT key,source,html,translated_at FROM translations ORDER BY key"):
        if key not in keys: continue
        record = {"key": key, "source": source, "html": translated_html, "translated_at": translated_at}
        _validate_record(record, len(rows) + 2)
        rows.append(record)
    encode = lambda record: json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    payload = (encode(METADATA) + "".join(encode(record) for record in rows)).encode("utf-8")
    if path.exists() and path.read_bytes() == payload: return len(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".google-cache-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()
    return len(rows)
