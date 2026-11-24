"""Exercise reviewed copy edits without invoking Copilot or changing real caches."""
import contextlib
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


if __name__ == "__main__":
    unittest.main()
