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
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
        self.assertEqual(list(polish.paragraphs(document(CHINESE * 120), "chapter", counts)), [])
        self.assertEqual(counts["too_long"], 1)


class PreviewAndApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="polish-tests-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.page = self.data / "pages/overview.json"
        self.page.parent.mkdir(parents=True)
        self.preview_dir = self.root / "preview"
        self.write_page()

    def tearDown(self):
        self.temporary.cleanup()

    def write_page(self, english=ENGLISH):
        soup = document(RICH_CHINESE, english)
        pre = soup.new_tag("pre")
        code = soup.new_tag("code")
        code.string = "const auto devices = instance.enumeratePhysicalDevices();\n"
        pre.append(code)
        soup.article.append(pre)
        self.page.write_text(json.dumps({"id": "overview", "title": "Physical devices", "html": str(soup), "stats": {"translated": 1, "total": 1}}, ensure_ascii=False), encoding="utf-8")

    def test_preview_receives_english_and_draft_and_only_reviewed_apply_changes_page(self):
        baseline = self.page.read_bytes()
        source = BeautifulSoup(json.loads(baseline)["html"], "html.parser")
        captured = []

        def answer(chapter, items, model):
            captured.append((chapter, items, model))
            return {item["id"]: item["Chinese"].replace("初始化以后", "初始化后") for item in items}

        with patch.object(polish, "copilot", side_effect=answer), contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", {}, 1, self.preview_dir, "test-model")
        self.assertEqual(self.page.read_bytes(), baseline, "Preview must leave the generated chapter untouched")
        chapter, items, model = captured[0]
        self.assertEqual((chapter, model), ("Physical devices", "test-model"))
        self.assertEqual(items[0]["English"], ENGLISH)
        self.assertIn("初始化以后", items[0]["Chinese"])
        self.assertIn("⟦0⟧", items[0]["Chinese"])
        self.assertIn("交换链", items[0]["protected"])
        report = json.loads((self.preview_dir / "review.json").read_text(encoding="utf-8"))["paragraphs"][0]
        self.assertEqual(report["status"], "edited")
        self.assertEqual(report["english"], ENGLISH)
        self.assertEqual(report["google"], source.select_one(".vt-zh").get_text())
        self.assertEqual(report["polished"], report["google"].replace("初始化以后", "初始化后"))

        reviewed = polish.read_cache(self.preview_dir / "polish.json")
        self.assertEqual(polish.apply_cache(self.data, ["overview"], reviewed), (1, 1))
        changed = json.loads(self.page.read_text(encoding="utf-8"))
        result = BeautifulSoup(changed["html"], "html.parser")
        self.assertEqual(result.select_one(".vt-en").get_text(), source.select_one(".vt-en").get_text())
        self.assertEqual(result.select_one(".vt-zh").get_text(), report["polished"])
        self.assertEqual(result.pre.code.get_text(), source.pre.code.get_text())
        for selector in (".vt-term", ".vt-zh a", ".vt-zh code"):
            self.assertEqual(str(result.select_one(selector)), str(source.select_one(selector)))
        self.assertEqual(changed["stats"]["polished"], 1)
        applied_bytes = self.page.read_bytes()
        self.assertEqual(polish.apply_cache(self.data, ["overview"], reviewed), (0, 0))
        self.assertEqual(self.page.read_bytes(), applied_bytes)

    def test_rejected_model_result_is_reviewable_and_never_enters_applied_cache(self):
        baseline = self.page.read_bytes()
        with patch.object(polish, "copilot", return_value={}), contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", {}, 1, self.preview_dir, None)
        report = json.loads((self.preview_dir / "review.json").read_text(encoding="utf-8"))["paragraphs"][0]
        self.assertEqual(report["status"], "rejected")
        self.assertIn("reason", report)
        self.assertEqual(polish.read_cache(self.preview_dir / "polish.json"), {})
        self.assertEqual(polish.apply_cache(self.data, ["overview"], {}), (0, 0))
        self.assertEqual(self.page.read_bytes(), baseline)

    def test_source_update_does_not_apply_a_previously_reviewed_edit(self):
        paragraph = first_paragraph(RICH_CHINESE)
        reviewed = {paragraph.key: paragraph.draft.replace("初始化以后", "初始化后")}
        self.write_page(english=ENGLISH.replace("supports", "does not support"))
        updated_source = self.page.read_bytes()
        self.assertEqual(polish.apply_cache(self.data, ["overview"], reviewed), (0, 0))
        self.assertEqual(self.page.read_bytes(), updated_source)

    def test_unchanged_result_is_recorded_to_avoid_repeat_preview_calls(self):
        def unchanged(_chapter, items, _model): return {item["id"]: item["Chinese"] for item in items}
        with patch.object(polish, "copilot", side_effect=unchanged), contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", {}, 1, self.preview_dir, None)
        reviewed = polish.read_cache(self.preview_dir / "polish.json")
        report = json.loads((self.preview_dir / "review.json").read_text(encoding="utf-8"))["paragraphs"][0]
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(polish.apply_cache(self.data, ["overview"], reviewed), (0, 0))
        with patch.object(polish, "copilot") as remote, contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", reviewed, 1, self.root / "second-preview", None)
        remote.assert_not_called()


class CopilotAdapterTests(unittest.TestCase):
    def test_cli_request_includes_both_sources_and_isolated_auth_without_real_process(self):
        paragraph = first_paragraph(RICH_CHINESE, english=ENGLISH + " See @reference for the example.")
        item = paragraph.request()
        expected = {paragraph.key: paragraph.draft}
        fake = SimpleNamespace(returncode=0, stdout="```json\n" + json.dumps(expected, ensure_ascii=False) + "\n```", stderr="")
        with patch.dict(os.environ, {"GITHUB_TOKEN": "unit-test-token", "UNRELATED_SECRET": "must-not-be-passed"}, clear=True), \
             patch.object(polish.shutil, "which", return_value="/mock/copilot"), \
             patch.object(polish.subprocess, "run", return_value=fake) as process:
            self.assertEqual(polish.copilot("Physical devices", [item], "test-model"), expected)
        command = process.call_args.args[0]
        prompt = command[command.index("-p") + 1]
        payload = json.loads(prompt.splitlines()[-1])
        self.assertEqual(payload["paragraphs"][0]["English"], item["English"])
        self.assertEqual(payload["paragraphs"][0]["Chinese"], item["Chinese"])
        self.assertNotIn("@reference", prompt, "Document text must not become a CLI file mention")
        self.assertIn("--model=test-model", command)
        options = process.call_args.kwargs
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertNotIn("UNRELATED_SECRET", options["env"])
        self.assertEqual(options["env"]["GITHUB_TOKEN"], "unit-test-token")
        self.assertNotEqual(Path(options["cwd"]).resolve(), MODULE_PATH.parent.parent)


class AutomaticWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="polish-auto-tests-")
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

    def add_page(self, page_id, *, english=ENGLISH, chinese=CHINESE, count=1):
        soup = BeautifulSoup('<article></article>', "html.parser")
        for index in range(count):
            pair = document(chinese, english + f" Stage {index}.").select_one(".vt-pair")
            soup.article.append(pair)
        path = self.data / "pages" / (page_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": page_id, "title": page_id, "html": str(soup)}, ensure_ascii=False), encoding="utf-8")
        if page_id not in self.pages:
            self.pages.append(page_id)

    def run_auto(self, **options):
        entries = polish.read_cache(self.cache)
        kwargs = dict(cache_file=self.cache, state_file=self.state, report_file=self.report,
                      limit=30, seconds=180, model="test-model", backfill=True)
        kwargs.update(options)
        with contextlib.redirect_stdout(io.StringIO()):
            return polish.auto_polish(self.data, self.pages, entries, **kwargs)

    @staticmethod
    def unchanged(_chapter, items, _model, **_options):
        return {item["id"]: item["Chinese"] for item in items}

    def test_inventory_backfill_advances_with_unchanged_results_without_repeat_calls(self):
        self.add_page("overview", count=3)
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto(limit=1)
            first = remote.call_args.args[1][0]["id"]
            self.run_auto(limit=1)
            self.assertNotEqual(remote.call_args.args[1][0]["id"], first)
            self.run_auto(limit=1)
        state = polish.read_state(self.state)
        self.assertEqual((state["eligible"], state["processed"], state["pending"]), (3, 3, 0))
        self.assertTrue(state["backfill_complete"])
        self.assertEqual(len(polish.read_cache(self.cache)), 3)
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()

    def test_new_and_changed_keys_keep_priority_over_older_backfill(self):
        self.add_page("old")
        self.add_page("modified")
        with patch.object(polish, "copilot") as remote:
            self.run_auto(backfill=False)
        remote.assert_not_called()
        self.add_page("modified", english=ENGLISH + " The original paragraph changed.")
        self.add_page("new")
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[1][0]["chapter"], "modified")
            self.assertEqual(polish.read_state(self.state)["priority_pending"], 1)
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[1][0]["chapter"], "new")
            self.run_auto(limit=1)
            self.assertEqual(remote.call_args.args[1][0]["chapter"], "old")

    def test_successful_batch_survives_later_service_failure_and_applies_before_exit(self):
        self.add_page("overview", count=8)
        calls = 0

        def answer(chapter, items, model, **options):
            nonlocal calls
            calls += 1
            if calls == 2: raise ValueError("Account unavailable")
            self.assertGreater(options["timeout"], 0)
            self.assertLessEqual(options["timeout"], 100)
            return {item["id"]: item["Chinese"].replace("初始化以后", "初始化后") for item in items}

        with patch.object(polish, "copilot", side_effect=answer):
            report = self.run_auto(limit=8)
        self.assertEqual(report["stopped_reason"], "service_error")
        self.assertEqual(report["applied"], 6)
        self.assertEqual(len(polish.read_cache(self.cache)), 6)
        self.assertEqual(polish.read_state(self.state)["pending"], 2)
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()
        self.assertEqual(polish.read_state(self.state)["pending"], 2, "Already polished artifact identities must remain stable")

    def test_no_auth_applies_old_v1_cache_without_ai_and_preserves_google_file(self):
        self.add_page("reviewed")
        self.add_page("pending")
        page = json.loads((self.data / "pages/reviewed.json").read_text(encoding="utf-8"))
        block = next(polish.paragraphs(BeautifulSoup(page["html"], "html.parser"), "reviewed"))
        self.cache.write_text(json.dumps({"version": 1, "entries": {block.key: block.draft.replace("初始化以后", "初始化后")}}, ensure_ascii=False), encoding="utf-8")
        google = self.root / "google.jsonl"
        google.write_bytes(b"immutable Google base cache\n")
        with patch.dict(os.environ, {}, clear=True), patch.object(polish, "copilot") as remote:
            report = self.run_auto()
        remote.assert_not_called()
        self.assertEqual(report["stopped_reason"], "no_auth")
        self.assertEqual(report["applied"], 1)
        self.assertEqual(google.read_bytes(), b"immutable Google base cache\n")
        self.assertIsNotNone(polish.read_state(self.state)["retry_after"])

    def test_rejected_input_cools_down_and_is_quarantined_after_bounded_retries(self):
        self.add_page("overview")
        with patch.object(polish, "copilot", return_value={}):
            self.run_auto()
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()
        for _ in range(2):
            state = polish.read_state(self.state)
            state["retry_after"] = "2000-01-01T00:00:00+00:00"
            for failure in state["failures"].values(): failure["retry_after"] = "2000-01-01T00:00:00+00:00"
            self.state.write_text(json.dumps(state), encoding="utf-8")
            with patch.object(polish, "copilot", return_value={}):
                self.run_auto()
        state = polish.read_state(self.state)
        self.assertEqual((state["pending"], state["rejected"]), (0, 1))
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()

    def test_all_individual_cooldowns_publish_earliest_global_retry_for_gate(self):
        self.add_page("overview", count=2)
        with patch.object(polish, "copilot"):
            self.run_auto(backfill=False)
        state = polish.read_state(self.state)
        first = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        second = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
        state["failures"] = {key: {"attempts": 1, "quarantined": False, "retry_after": date} for key, date in zip(state["keys"], [first, second])}
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(polish, "copilot") as remote:
            self.run_auto()
        remote.assert_not_called()
        self.assertEqual(polish.read_state(self.state)["retry_after"], first)

    def test_malformed_batch_records_per_paragraph_attempts_for_recovery(self):
        self.add_page("overview")
        with patch.object(polish, "copilot", side_effect=polish.InvalidPolishResponse("Invalid JSON")):
            report = self.run_auto()
        self.assertEqual(report["stopped_reason"], "rejected_batch")
        self.assertEqual(report["paragraphs"][0]["reason"], "Invalid JSON")
        state = polish.read_state(self.state)
        self.assertEqual(next(iter(state["failures"].values()))["attempts"], 1)
        self.assertFalse(polish.read_cache(self.cache))

    def test_preview_splits_long_blocks_by_input_size_and_auto_bounds_timeout(self):
        self.add_page("overview", english=ENGLISH * 20, chinese=CHINESE * 25, count=3)
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote, contextlib.redirect_stdout(io.StringIO()):
            polish.preview(self.data, "overview", {}, 3, self.root / "preview", "test-model")
        self.assertGreater(remote.call_count, 1)
        self.assertTrue(all(len(call.args[1]) < 3 for call in remote.call_args_list))
        with patch.object(polish, "copilot", side_effect=self.unchanged) as remote:
            self.run_auto(limit=1, seconds=5)
        self.assertGreater(remote.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(remote.call_args.kwargs["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
