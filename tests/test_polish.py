"""Exercise reviewed copy edits without invoking Copilot or changing real caches."""
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/polish.py"
spec = importlib.util.spec_from_file_location("vulkan_polish_under_test", MODULE_PATH)
polish = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = polish
spec.loader.exec_module(polish)

ENGLISH = (
    "After initializing the instance, select a physical device that supports "
    "the required graphics operations and configure its queues."
)
CHINESE = "完成实例的初始化以后，我们需要选择支持所需图形操作的物理设备，并继续配置用于绘制的队列。"
RICH_CHINESE = (
    '完成实例的初始化以后，我们需要按照<span class="vt-term" data-term="swap chain" title="swap chain">交换链</span>'
    '的规则调用<code>vk::raii::Device device{\n    physicalDevice\n};</code>，'
    '参考<a href="/?page=01_Overview#queues" title="队列说明">对应章节</a>继续配置，'
    '并使用 Vulkan 1.4 中的 VkRenderingInfoKHR 与 VK_SUCCESS 检查至少 2 个可用队列。'
)


def document(chinese=CHINESE, english=ENGLISH):
    soup = BeautifulSoup('<article><div class="vt-pair"><p class="vt-en"></p><p class="vt-zh"></p></div></article>', "html.parser")
    soup.select_one(".vt-en").string = english
    for child in list(BeautifulSoup(chinese, "html.parser").contents):
        soup.select_one(".vt-zh").append(child)
    return soup


def first_paragraph(chinese=CHINESE, english=ENGLISH, page_id="overview"):
    return next(polish.paragraphs(document(chinese, english), page_id))


class ParagraphSafetyTests(unittest.TestCase):
    def test_minimal_fluency_edit_keeps_the_rest_of_the_sentence(self):
        paragraph = first_paragraph()
        paragraph.restore(paragraph.draft.replace("初始化以后", "初始化后"))
        self.assertEqual(paragraph.chinese.get_text(), CHINESE.replace("初始化以后", "初始化后"))

    def test_inline_nodes_versions_identifiers_and_numbers_are_frozen(self):
        paragraph = first_paragraph(RICH_CHINESE)
        term = paragraph.chinese.select_one(".vt-term")
        link = paragraph.chinese.select_one("a")
        code = paragraph.chinese.select_one("code")
        snapshots = {"term": str(term), "link": str(link), "code": str(code), "code_text": code.get_text()}
        prose = polish.MARKER.sub("", paragraph.draft)
        for protected_value in ("交换链", "对应章节", "vk::raii::Device", "Vulkan", "1.4", "VkRenderingInfoKHR", "VK_SUCCESS", "2"):
            self.assertNotIn(protected_value, prose)
        paragraph.restore(paragraph.draft.replace("初始化以后", "初始化后"))
        self.assertEqual(str(paragraph.chinese.select_one(".vt-term")), snapshots["term"])
        self.assertEqual(str(paragraph.chinese.select_one("a")), snapshots["link"])
        self.assertEqual(str(paragraph.chinese.select_one("code")), snapshots["code"])
        self.assertEqual(paragraph.chinese.select_one("code").get_text(), snapshots["code_text"])
        self.assertIn("Vulkan 1.4 中的 VkRenderingInfoKHR 与 VK_SUCCESS", paragraph.chinese.get_text())
        self.assertIn("至少 2 个可用队列", paragraph.chinese.get_text())

    def test_replacing_any_protected_kind_is_rejected_before_dom_changes(self):
        for original, replacement in (
            ("交换链", "缓冲帧"), ("对应章节", '<a href="https://example.org">错误链接</a>'),
            ("vk::raii::Device", "vk::raii::Instance"), ("1.4", "1.3"),
            ("VkRenderingInfoKHR", "VkRenderPassCreateInfo"), ("2", "3"),
        ):
            with self.subTest(protected=original):
                paragraph = first_paragraph(RICH_CHINESE)
                before = str(paragraph.chinese)
                index = next(index for index, item in enumerate(paragraph.protected) if original in str(item))
                edited = paragraph.draft.replace(f"⟦{index}⟧", replacement, 1)
                with self.assertRaises(ValueError): paragraph.restore(edited)
                self.assertEqual(str(paragraph.chinese), before)

    def test_missing_duplicate_reordered_and_unknown_markers_are_rejected(self):
        paragraph = first_paragraph(RICH_CHINESE)
        original = str(paragraph.chinese)
        reordered = polish.MARKER.sub(lambda match: {"⟦0⟧": "⟦1⟧", "⟦1⟧": "⟦0⟧"}.get(match.group(), match.group()), paragraph.draft)
        for edited in (
            paragraph.draft.replace("⟦0⟧", "", 1),
            paragraph.draft.replace("⟦0⟧", "⟦0⟧⟦0⟧", 1),
            paragraph.draft.replace("⟦0⟧", "⟦999⟧", 1), reordered,
        ):
            with self.subTest(edited=edited):
                with self.assertRaises(ValueError): paragraph.restore(edited)
                self.assertEqual(str(paragraph.chinese), original)

    def test_large_rewrite_new_facts_and_markup_are_rejected(self):
        paragraph = first_paragraph()
        original = str(paragraph.chinese)
        for edited in (
            "为了获得更好的性能，我们应该重新安排所有资源的初始化过程，并为后续的渲染工作提供更加灵活且完整的接口。",
            paragraph.draft + "需要支持 Vulkan 1.5。",
            paragraph.draft + "<script>执行其他操作</script>",
            paragraph.draft + "\n继续执行。", None,
        ):
            with self.subTest(edited=edited):
                with self.assertRaises(ValueError): paragraph.restore(edited)
                self.assertEqual(str(paragraph.chinese), original)

    def test_original_source_change_invalidates_the_paragraph_identity(self):
        original = first_paragraph()
        self.assertEqual(first_paragraph().key, original.key)
        self.assertNotEqual(first_paragraph(english=ENGLISH.replace("supports", "does not support")).key, original.key)
        self.assertNotEqual(first_paragraph(chinese=CHINESE.replace("初始化以后", "初始化后")).key, original.key)
        self.assertNotEqual(first_paragraph(page_id="other/chapter").key, original.key)

    def test_conditions_negation_quantifiers_and_order_cannot_change(self):
        chinese = "提交绘制命令之前，必须确认至少一个队列已经准备完成，如果资源仍在使用，就不能立即释放相关内存。"
        for old, new in (("必须", "可以"), ("至少", "所有"), ("如果", "因为"), ("不能", "能够"), ("之前", "之后")):
            with self.subTest(assertion=old):
                paragraph = first_paragraph(chinese)
                with self.assertRaises(ValueError): paragraph.restore(paragraph.draft.replace(old, new))

    def test_short_headings_and_table_leaves_are_eligible_with_small_edit_budget(self):
        soup = BeautifulSoup('<div class="vt-pair"><h2 class="vt-en">Select a physical device</h2><h2 class="vt-zh">选择物理设备</h2></div><table><tr><td><span class="vt-pair"><span class="vt-en">Queue configuration</span><span class="vt-zh">配置设备队列</span></span></td></tr></table>', "html.parser")
        blocks = list(polish.paragraphs(soup, "chapter"))
        self.assertEqual([block.chinese.name for block in blocks], ["h2", "span"])
        with self.assertRaises(ValueError): blocks[0].restore("配置逻辑队列")

    def test_existing_polished_artifact_keeps_identity_until_source_really_changes(self):
        soup = document()
        block = next(polish.paragraphs(soup, "chapter"))
        original_key = block.key
        block.restore(block.draft.replace("初始化以后", "初始化后"))
        self.assertEqual(next(polish.paragraphs(soup, "chapter")).key, original_key)
        soup.select_one(".vt-en").string = ENGLISH.replace("supports", "does not support")
        self.assertNotEqual(next(polish.paragraphs(soup, "chapter")).key, original_key)

    def test_long_prose_up_to_sync_limit_is_eligible_and_oversized_is_counted(self):
        self.assertEqual(len(list(polish.paragraphs(document(CHINESE * 30, ENGLISH * 12), "chapter"))), 1)
        counts = {}
        # Counter is the same caller-facing diagnostic accumulator used by the scan.
        from collections import Counter
        counts = Counter(counts)
        self.assertEqual(list(polish.paragraphs(document(CHINESE * 5000), "chapter", counts)), [])
        self.assertEqual(counts["too_long"], 1)


def confirmed(chapter, edits=None):
    return {"chapter_id": chapter["id"], "chapter_key": chapter["key"],
            "reviewed_complete": True, "reviewed_count": chapter["editable_count"],
            "edits": edits or {}}


class ChapterWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="polish-chapter-tests-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.cache = self.root / "polish.json"
        self.state = self.root / "polish-state.json"
        self.report = self.root / "report.json"
        self.pages = []
        self.environment = patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "unit-test-token"}, clear=True)
        self.cli = patch.object(polish.shutil, "which", return_value="/mock/copilot")
        self.environment.start()
        self.cli.start()

    def tearDown(self):
        self.cli.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def page_file(self, page_id):
        return self.data / "pages" / (page_id + ".json")

    def add_page(self, page_id, *, count=1, english=ENGLISH, chinese=RICH_CHINESE, duplicate=False):
        soup = BeautifulSoup('<article><h1>Chapter title</h1></article>', "html.parser")
        for index in range(count):
            text = english if count == 1 or duplicate else english + f" Stage {index}."
            soup.article.append(document(chinese, text).select_one(".vt-pair"))
        pending = soup.new_tag("div", attrs={"class": "vt-pair vt-pending"})
        source = soup.new_tag("p", attrs={"class": "vt-en"})
        source.string = "This not-yet-translated paragraph is still full chapter context."
        pending.append(source)
        soup.article.append(pending)
        pre = soup.new_tag("pre")
        code = soup.new_tag("code")
        code.string = "DO_NOT_SEND_CODE_LISTING_CONTENT();\n"
        pre.append(code)
        soup.article.append(pre)
        path = self.page_file(page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": page_id, "title": page_id,
                                   "titleZh": "中文章节标题", "html": str(soup)}, ensure_ascii=False), encoding="utf-8")
        if page_id not in self.pages:
            self.pages.append(page_id)

    @staticmethod
    def unchanged(chapter, _items, _model, **_options):
        return confirmed(chapter)

    def run_auto(self, **options):
        kwargs = dict(cache_file=self.cache, state_file=self.state, report_file=self.report,
                      limit=5, seconds=420, model="test-model", backfill=True)
        kwargs.update(options)
        with contextlib.redirect_stdout(io.StringIO()):
            return polish.auto_polish(self.data, self.pages, polish.read_cache(self.cache), **kwargs)

    def test_preview_is_one_complete_chapter_even_with_legacy_paragraph_limit(self):
        self.add_page("overview", count=8)
        baseline = self.page_file("overview").read_bytes()
        destination = self.root / "preview"
        captured = []

        def answer(chapter, items, model, **options):
            captured.append((chapter, items, model, options))
            editable = [item for item in items if item["editable"]]
            return confirmed(chapter, {editable[0]["id"]: editable[0]["Chinese"].replace("初始化以后", "初始化后")})

        with patch.object(polish, "copilot", side_effect=answer) as remote, contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", {}, 1, destination, "test-model", seconds=420)
        remote.assert_called_once()
        chapter, units, model, options = captured[0]
        self.assertEqual((chapter["id"], chapter["titleZh"] if "titleZh" in chapter else chapter["title_zh"]), ("overview", "中文章节标题"))
        self.assertEqual(chapter["editable_count"], 8)
        self.assertEqual([item["id"] for item in units if item["editable"]], [str(index) for index in range(1, 9)])
        self.assertTrue(any(item["kind"] == "untranslated" and "not-yet-translated" in (item["English"] or "") for item in units))
        self.assertNotIn("DO_NOT_SEND_CODE_LISTING_CONTENT", json.dumps(units))
        self.assertEqual(self.page_file("overview").read_bytes(), baseline)
        review = json.loads((destination / "review.json").read_text(encoding="utf-8"))
        self.assertTrue(review["complete"])
        self.assertEqual(len(review["paragraphs"]), 8)
        approved = polish.read_cache(destination / "polish.json")
        self.assertEqual(len(approved), 1)
        self.assertEqual(polish.apply_cache(self.data, self.pages, approved), (1, 1))
        self.assertEqual(polish.apply_cache(self.data, self.pages, approved), (0, 0))

    def test_each_auto_call_has_one_chapter_and_progress_counts_chapters(self):
        self.add_page("first", count=7)
        self.add_page("second", count=3)
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto(limit=1)
            self.assertEqual(remote.call_count, 1)
            self.assertEqual(remote.call_args.args[0]["id"], "first")
            self.assertEqual(remote.call_args.args[0]["editable_count"], 7)
            self.run_auto(limit=1)
            self.assertEqual(remote.call_count, 2)
            self.assertEqual(remote.call_args.args[0]["id"], "second")
        state = polish.read_state(self.state)
        self.assertEqual((state["version"], state["eligible"], state["processed"], state["pending"]), (2, 2, 2, 0))
        self.assertTrue(state["backfill_complete"])
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()

    def test_batch_deadline_does_not_mark_the_last_chapter_as_a_failure(self):
        self.add_page("first")
        self.add_page("second")
        clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 1, 2, 380, 390]))

        def answer(chapter, items, model, *, timeout):
            if chapter["id"] == "second":
                self.assertEqual(timeout, 30)
                raise subprocess.TimeoutExpired(["copilot"], timeout)
            return self.unchanged(chapter, items, model)

        with patch.object(polish, "time", clock), patch.object(polish, "copilot", side_effect=answer):
            report = self.run_auto()
        state = polish.read_state(self.state)
        self.assertEqual((state["processed"], state["pending"], state["failures"]), (1, 1, {}))
        self.assertEqual((report["attempted"], report["stopped_reason"]), (2, "time_budget"))
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto()
        remote.assert_called_once()
        self.assertEqual(remote.call_args.args[0]["id"], "second")

    def test_new_or_modified_chapters_keep_absolute_priority(self):
        self.add_page("old")
        self.add_page("modified")
        with patch.object(polish, "copilot") as remote:
            self.run_auto(backfill=False)
        remote.assert_not_called()
        self.add_page("modified", english=ENGLISH + " The source changed.")
        self.add_page("new")
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[0]["id"], "modified")
            self.assertEqual(polish.read_state(self.state)["priority_pending"], 1)
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[0]["id"], "new")
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[0]["id"], "old")

    def test_v1_partial_progress_and_cooldown_do_not_masquerade_as_complete_chapter(self):
        self.add_page("overview", count=2)
        chapter = polish.load_chapter(self.data, "overview", {})
        block = chapter.editable["1"]
        old_value = block.draft.replace("初始化以后", "初始化后")
        self.cache.write_text(json.dumps({"version": 1, "entries": {block.key: old_value}}, ensure_ascii=False), encoding="utf-8")
        self.state.write_text(json.dumps({"version": 1, "keys": [block.key], "priority": [], "failures": {},
                                          "pending": 0, "retry_after": "2999-01-01T00:00:00+00:00", "stopped_reason": "cooldown"}), encoding="utf-8")
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto()
        remote.assert_called_once()
        first = next(item for item in remote.call_args.args[1] if item["editable"])
        self.assertIn("初始化后", first["Chinese"])
        self.assertNotIn("初始化以后", first["Chinese"])
        self.assertEqual(polish.read_cache(self.cache)[block.key], old_value, "Sparse omission must retain previously accepted v1 corrections")
        self.assertEqual(polish.read_state(self.state)["processed"], 1)

    def test_invalid_suggestions_are_rejected_but_confirmed_chapter_is_not_rebilled(self):
        self.add_page("overview", count=3)

        def answer(chapter, items, _model, **_options):
            editable = [item for item in items if item["editable"]]
            return confirmed(chapter, {"1": editable[0]["Chinese"].replace("初始化以后", "初始化后"),
                                       "2": editable[1]["Chinese"].replace("⟦0⟧", "", 1)})

        with patch.object(polish, "copilot", side_effect=answer):
            report = self.run_auto()
        self.assertEqual(report["chapters"][0]["status"], "complete_with_rejections")
        self.assertEqual((report["chapters"][0]["edited"], report["chapters"][0]["rejected"]), (1, 1))
        self.assertEqual((len(polish.read_cache(self.cache)), polish.read_state(self.state)["pending"]), (1, 0))
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()

    def test_missing_confirmation_wrong_identity_and_invented_ids_never_complete(self):
        self.add_page("overview")
        chapter = polish.load_chapter(self.data, "overview", {})
        for answer in ({}, confirmed({**chapter.metadata, "key": "a" * 64}),
                       {**confirmed(chapter.metadata), "reviewed_complete": False},
                       {**confirmed(chapter.metadata), "reviewed_count": 999},
                       confirmed(chapter.metadata, {"999": "错误内容"})):
            with self.subTest(answer=answer):
                with self.assertRaises(polish.InvalidPolishResponse): polish.review_chapter(chapter, answer, {})

    def test_bad_chapter_response_does_not_block_next_chapter(self):
        self.add_page("first")
        self.add_page("second")
        calls = 0

        def answer(chapter, items, model, **options):
            nonlocal calls
            calls += 1
            if calls == 1: raise polish.InvalidPolishResponse("Truncated model JSON")
            return confirmed(chapter)

        with patch.object(polish, "copilot", side_effect=answer) as remote:
            report = self.run_auto(limit=2)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual([item["status"] for item in report["chapters"]], ["rejected_response", "complete"])
        state = polish.read_state(self.state)
        self.assertEqual((state["processed"], state["pending"]), (1, 1))
        self.assertIsNotNone(state["retry_after"])

    def test_successful_chapter_is_saved_if_later_service_fails_and_cached_edits_still_apply(self):
        self.add_page("first")
        self.add_page("second")
        calls = 0

        def answer(chapter, items, model, **options):
            nonlocal calls
            calls += 1
            if calls == 2: raise ValueError("Account or quota unavailable")
            self.assertLessEqual(options["timeout"], 180)
            block = next(item for item in items if item["editable"])
            return confirmed(chapter, {block["id"]: block["Chinese"].replace("初始化以后", "初始化后")})

        with patch.object(polish, "copilot", side_effect=answer):
            report = self.run_auto(limit=2)
        self.assertEqual((report["stopped_reason"], report["applied"]), ("service_error", 1))
        self.assertEqual((len(polish.read_cache(self.cache)), polish.read_state(self.state)["processed"]), (1, 1))
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()

    def test_no_auth_preserves_google_and_applies_old_v1_edits_without_marking_full_review(self):
        self.add_page("overview")
        chapter = polish.load_chapter(self.data, "overview", {})
        block = chapter.editable["1"]
        self.cache.write_text(json.dumps({"version": 1, "entries": {block.key: block.draft.replace("初始化以后", "初始化后")}}, ensure_ascii=False), encoding="utf-8")
        google = self.root / "google.jsonl"
        google.write_bytes(b"immutable Google cache\n")
        with patch.dict(os.environ, {}, clear=True), patch.object(polish, "copilot") as remote:
            report = self.run_auto()
        remote.assert_not_called()
        self.assertEqual((report["stopped_reason"], report["applied"]), ("no_auth", 1))
        self.assertEqual(polish.read_state(self.state)["processed"], 0)
        self.assertEqual(google.read_bytes(), b"immutable Google cache\n")

    def test_oversized_chapter_is_reported_without_splitting_or_calling_model(self):
        self.add_page("overview", count=3)
        with patch.object(polish, "MAX_CHAPTER_INPUT_BYTES", 1000), patch.object(polish, "copilot") as remote:
            report = self.run_auto()
        remote.assert_not_called()
        self.assertEqual((report["deferred"], report["pending"]), (1, 0))
        self.assertGreater(report["deferred_chapters"][0]["input_bytes"], 1000)
        self.assertFalse(polish.read_state(self.state)["backfill_complete"])

    def test_fingerprint_is_stable_after_apply_and_changes_with_either_title_or_source(self):
        self.add_page("overview")
        original = polish.load_chapter(self.data, "overview", {})
        block = original.editable["1"]
        entries = {block.key: block.draft.replace("初始化以后", "初始化后")}
        polish.apply_cache(self.data, self.pages, entries)
        self.assertEqual(polish.load_chapter(self.data, "overview", entries).key, original.key)
        page = json.loads(self.page_file("overview").read_text(encoding="utf-8"))
        page["titleZh"] = "更正后的中文章节标题"
        self.page_file("overview").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        self.assertNotEqual(polish.load_chapter(self.data, "overview", entries).key, original.key)

    def test_duplicate_cache_keys_have_one_editable_id_and_no_conflicting_writes(self):
        self.add_page("overview", count=2, duplicate=True)
        chapter = polish.load_chapter(self.data, "overview", {})
        self.assertEqual(len(chapter.editable), 1)
        self.assertTrue(any(item.get("duplicate_of") == "1" and not item["editable"] for item in chapter.units))
        before = chapter.bases[chapter.editable["1"].key].chinese.get_text()
        edits = {"1": chapter.editable["1"].draft.replace("初始化以后", "初始化后")}
        updated, audit, complete = polish.review_chapter(chapter, confirmed(chapter.metadata, edits), {})
        self.assertTrue(complete)
        self.assertEqual(len(updated), 1)
        self.assertEqual(audit[0]["google"], before)
        self.assertEqual(chapter.bases[chapter.editable["1"].key].chinese.get_text(), before)

    def test_short_translated_labels_can_be_corrected_but_terms_stay_protected(self):
        soup = BeautifulSoup('<div class="vt-pair"><h2 class="vt-en">Attribution</h2><h2 class="vt-zh">归属</h2></div>', "html.parser")
        block = next(polish.paragraphs(soup, "chapter"))
        block.restore("署名")
        self.assertEqual(block.chinese.get_text(), "署名")


class CopilotAdapterTests(unittest.TestCase):
    def test_full_long_chapter_goes_through_stdin_not_windows_argv(self):
        chapter = {"id": "long-chapter", "key": "a" * 64, "title": "Long chapter", "title_zh": "长章节", "editable_count": 1}
        units = [{"id": "1", "editable": True, "English": (ENGLISH + " See @reference. ") * 240,
                  "Chinese": CHINESE * 140, "protected": []}]
        expected = confirmed(chapter)
        result = SimpleNamespace(returncode=0, stdout="```json\n" + json.dumps(expected) + "\n```", stderr="")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "unit-test-token", "UNRELATED_SECRET": "never-pass"}, clear=True), patch.object(polish.shutil, "which", return_value="/mock/copilot"), patch.object(polish, "_run_cli", return_value=result) as process:
            self.assertEqual(polish.copilot(chapter, units, "test-model"), expected)
        command = process.call_args.args[0]
        options = process.call_args.kwargs
        self.assertNotIn("-p", command)
        self.assertIn("--model=test-model", command)
        prompt = process.call_args.args[1]
        self.assertGreater(len(prompt), 32767)
        self.assertLess(len(" ".join(command)), 4000)
        self.assertNotIn("@reference", prompt)
        payload = json.loads(prompt.splitlines()[-1])
        self.assertEqual(payload["chapter"], chapter)
        self.assertEqual(payload["blocks"][0]["English"], units[0]["English"])
        self.assertEqual(payload["blocks"][0]["Chinese"], units[0]["Chinese"])
        self.assertNotIn("UNRELATED_SECRET", options["env"])
        self.assertEqual(options["env"]["GITHUB_TOKEN"], "unit-test-token")
        self.assertNotEqual(Path(options["cwd"]).resolve(), MODULE_PATH.parent.parent)

    def test_duplicate_json_edit_ids_are_rejected_without_guessing(self):
        result = SimpleNamespace(returncode=0, stdout='{"edits":{"1":"甲","1":"乙"}}', stderr="")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "unit-test-token"}, clear=True), patch.object(polish.shutil, "which", return_value="/mock/copilot"), patch.object(polish, "_run_cli", return_value=result):
            with self.assertRaises(polish.InvalidPolishResponse): polish.copilot("chapter", [], None)


class ProcessIsolationTests(unittest.TestCase):
    def test_stdin_roundtrip_uses_a_local_owned_process(self):
        with tempfile.TemporaryDirectory(prefix="polish-stdin-test-") as directory:
            prompt = "完整章节通过标准输入传输。" * 4000
            result = polish._run_cli([sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
                                     prompt, cwd=directory, env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=10)
        self.assertEqual((result.returncode, result.stdout), (0, prompt))

    @unittest.skipIf(os.name == "nt", "Windows process-tree behavior is mocked; managed Windows denies taskkill")
    def test_timeout_reaps_native_child_instead_of_starting_overlapping_work(self):
        with tempfile.TemporaryDirectory(prefix="polish-process-tree-test-") as directory:
            marker = Path(directory) / "child-survived.txt"
            ready = Path(directory) / "child-started.txt"
            child = f"import pathlib,time; time.sleep(1.4); pathlib.Path({str(marker)!r}).write_text('survived')"
            parent = ("import pathlib,subprocess,sys,time; "
                      f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                      f"pathlib.Path({str(ready)!r}).write_text('started'); time.sleep(8)")
            with self.assertRaises(subprocess.TimeoutExpired):
                polish._run_cli([sys.executable, "-c", parent], "", cwd=directory,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=0.6)
            self.assertTrue(ready.exists(), "The regression must actually start the native child")
            time.sleep(1.6)
            self.assertFalse(marker.exists(), "A timed-out wrapper must not leave its child running")

    def test_posix_timeout_kills_the_separate_process_group_and_drains_pipes(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [subprocess.TimeoutExpired(["cli"], 0.1), ("", "")]
        operating_system = SimpleNamespace(name="posix", killpg=Mock())
        with patch.object(polish, "os", operating_system), patch.object(polish.signal, "SIGKILL", 9, create=True), \
             patch.object(polish.subprocess, "Popen", return_value=process) as launch:
            with self.assertRaises(subprocess.TimeoutExpired):
                polish._run_cli(["cli"], "whole chapter", cwd="isolated", env={}, timeout=0.1)
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        operating_system.killpg.assert_called_once_with(12345, 9)
        self.assertEqual(process.communicate.call_count, 2)

    def test_failed_windows_tree_cleanup_stops_globally_instead_of_continuing(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [subprocess.TimeoutExpired(["cli"], 0.1), ("", "")]
        operating_system = SimpleNamespace(name="nt", environ={"SystemRoot": r"C:\Windows"})
        with patch.object(polish, "os", operating_system), patch.object(polish.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
             patch.object(polish.subprocess, "Popen", return_value=process), \
             patch.object(polish.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as terminate:
            with self.assertRaisesRegex(ValueError, "could not be confirmed stopped"):
                polish._run_cli(["cli"], "whole chapter", cwd="isolated", env={}, timeout=0.1)
        self.assertEqual(terminate.call_args.args[0][1:], ["/PID", "12345", "/T", "/F"])
        process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
