"""Exercise reader-visible term problems through the actual chapter review pipeline."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import polish


MIPMAP = '<span class="vt-term" data-english="mipmap">多级纹理</span>'
INLINE_CODE = '<code><span class="vt-term" data-term="unwanted">MIP_TOKEN</span></code>'
EDITABLE = (
    '<div class="vt-pair"><p class="vt-en">Use the mipmap and MIP_TOKEN.</p>'
    f'<p class="vt-zh">使用 {MIPMAP}（mipmap）和 {INLINE_CODE}。</p></div>'
)
REVIEWED = (
    '<div class="vt-pair"><p class="vt-en">Sample the mipmap.</p>'
    f'<p class="vt-zh" data-vt-reviewed="true">按 {MIPMAP} mipmap 采样。</p></div>'
)


def confirmation(metadata, **result):
    return {
        "chapter_id": metadata["id"], "chapter_key": metadata["key"],
        "reviewed_complete": True, "reviewed_count": metadata["editable_count"],
        "edits": {}, **result,
    }


class TermViewReviewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.page = self.data / "pages" / "mipmaps.json"
        self.page.parent.mkdir()
        self.cache = self.data / "polish.json"
        self.state = self.data / "polish-state.json"
        self.report = self.data / "report.json"

    def write_page(self, html, page_id="mipmaps"):
        page = {"id": page_id, "title": "Mipmaps", "titleZh": "多级纹理", "html": html}
        path = self.page.with_name(page_id + ".json")
        path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")

    def run_auto(self, page_ids):
        with contextlib.redirect_stdout(io.StringIO()):
            return polish.auto_polish(
                self.data, page_ids, polish.read_cache(self.cache),
                cache_file=self.cache, state_file=self.state, report_file=self.report,
                backfill=True, model="test-model",
            )

    def mock_copilot(self, answer):
        # Only Copilot is mocked; Node still runs the shared reader text projection.
        real_which = polish.shutil.which

        def lookup(name):
            return "/mock/copilot" if name == "copilot" else real_which(name)

        mocks = contextlib.ExitStack()
        self.addCleanup(mocks.close)
        mocks.enter_context(patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test"}))
        mocks.enter_context(patch.object(polish.shutil, "which", side_effect=lookup))
        return mocks.enter_context(patch.object(polish, "copilot", side_effect=answer))

    def test_model_sees_text_from_both_reader_modes_with_code_preserved(self):
        self.write_page(EDITABLE + REVIEWED)
        chapter = polish.load_chapter(self.data, "mipmaps", {})
        editable = next(unit for unit in chapter.units if unit["editable"])
        self.assertEqual(editable["reader"]["off"], "使用多级纹理（mipmap）和 MIP_TOKEN。")
        self.assertEqual(editable["reader"]["on"], "使用 mipmap 和 MIP_TOKEN。")
        self.assertFalse(editable.get("display_findings"))
        reviewed = next(unit for unit in chapter.units if unit.get("issue_only"))
        self.assertFalse(reviewed["editable"])
        self.assertEqual(reviewed["reader"]["off"], "按多级纹理 mipmap 采样。")
        self.assertEqual(reviewed["reader"]["on"], "按 mipmap mipmap 采样。")
        self.assertEqual(reviewed["display_findings"], ["mipmap mipmap"])
        with self.assertRaises(polish.InvalidPolishResponse):
            polish.review_chapter(chapter, confirmation(chapter.metadata, edits={
                reviewed["id"]: "使用多级纹理进行采样。",
            }), {})

    def test_read_only_display_issue_keeps_suggestion_and_reuses_completed_check(self):
        self.write_page(REVIEWED)
        text_before = self.page.read_bytes()
        proposal = {"reason": "保留英文术语时 mipmap 重复。", "proposed": "按多级纹理采样。"}

        def flag_duplicate(metadata, items, _model, **_options):
            self.assertEqual(metadata["editable_count"], 0)
            item = next(unit for unit in items if unit.get("issue_only"))
            return confirmation(metadata, issues={item["id"]: proposal})

        model = self.mock_copilot(flag_duplicate)
        first = self.run_auto(["mipmaps"])
        self.assertEqual(model.call_count, 1)
        issue = next(row for row in first["paragraphs"] if row["status"] == "needs_review")
        self.assertEqual(issue["english"], "Sample the mipmap.")
        self.assertEqual(issue["english_terms"], "按 mipmap mipmap 采样。")
        self.assertEqual(issue["proposed"], proposal["proposed"])
        stored = next(iter(polish.read_state(self.state)["review_issues"].values()))[0]
        self.assertEqual(stored["proposed"], proposal["proposed"])
        self.assertEqual(polish.read_cache(self.cache), {})
        self.assertEqual(self.page.read_bytes(), text_before)
        self.assertEqual(self.run_auto(["mipmaps"])["pending"], 0)
        self.assertEqual(model.call_count, 1)
        self.write_page(REVIEWED.replace("Sample the mipmap.", "Sample the chosen mipmap."))
        self.run_auto(["mipmaps"])
        self.assertEqual(model.call_count, 2)

    def test_legacy_completion_backfills_only_visible_anomalies_once(self):
        self.write_page(EDITABLE + REVIEWED)
        self.write_page(EDITABLE, page_id="clean")
        pages = ["clean", "mipmaps"]
        model = self.mock_copilot(lambda metadata, *args, **kwargs: confirmation(metadata))
        self.run_auto(pages)
        state = polish.read_state(self.state)
        self.assertEqual(state["processed"], 2)
        state.pop("display_checked")
        self.state.write_text(json.dumps(state), encoding="utf-8")
        model.reset_mock()

        self.run_auto(pages)
        self.assertEqual([call.args[0]["id"] for call in model.call_args_list], ["mipmaps"])
        state = polish.read_state(self.state)
        self.assertEqual(state["processed"], 2)
        self.assertEqual(set(state["display_checked"]), {state["chapters"]["mipmaps"]})
        self.run_auto(pages)
        self.assertEqual(model.call_count, 1)

    def test_title_and_navigation_reports_refresh_if_only_navigation_changes(self):
        self.write_page(EDITABLE)
        page = json.loads(self.page.read_text(encoding="utf-8"))
        page["titleZhHtml"] = MIPMAP + " mipmap"
        self.page.write_text(json.dumps(page), encoding="utf-8")
        catalog = {"navigation": [
            {"title": "Sampling", "depth": 0, "titleZhHtml": MIPMAP + " mipmap 分组"},
            {"title": "Mipmaps", "depth": 1, "id": "mipmaps"},
        ]}
        path = self.data / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")

        def flag_labels(metadata, units, _model, **_options):
            labels = {unit["kind"]: unit for unit in units if unit["kind"] in {"title", "navigation"}}
            self.assertEqual(set(labels), {"title", "navigation"})
            self.assertTrue(all(unit.get("issue_only") and not unit["editable"] for unit in labels.values()))
            issues = {unit["id"]: {"reason": "英文术语在标题中重复。", "proposed": "多级纹理"}
                      for unit in labels.values()}
            return confirmation(metadata, issues=issues)

        model = self.mock_copilot(flag_labels)
        report = self.run_auto(["mipmaps"])
        reported = {row["id"]: row for row in report["paragraphs"] if row["status"] == "needs_review"}
        self.assertEqual(reported["title"]["english_terms"], "mipmap mipmap")
        self.assertEqual(reported["nav-0"]["english_terms"], "mipmap mipmap 分组")
        self.assertEqual(polish.read_cache(self.cache), {})
        self.run_auto(["mipmaps"])
        self.assertEqual(model.call_count, 1)
        catalog["navigation"][0]["titleZhHtml"] = MIPMAP + " mipmap 设置分组"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        report = self.run_auto(["mipmaps"])
        nav = next(row for row in report["paragraphs"] if row["id"] == "nav-0")
        self.assertEqual(nav["english_terms"], "mipmap mipmap 设置分组")
        self.assertEqual(model.call_count, 2)
