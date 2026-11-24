import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

spec = importlib.util.spec_from_file_location("mirror_sync", Path(__file__).parents[1] / "scripts/sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class UpstreamRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.origin = self.directory / "origin"
        subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(self.origin)], check=True)
        self.first = self.commit("first")
        self.latest = self.commit("latest")

    def git(self, source, *args):
        return subprocess.check_output(["git", "-C", str(source), *args], stderr=subprocess.PIPE, text=True).strip()

    def commit(self, contents):
        (self.origin / "tutorial.adoc").write_text(contents, encoding="utf-8")
        self.git(self.origin, "add", "tutorial.adoc")
        self.git(self.origin, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--quiet", "-m", contents)
        return self.git(self.origin, "rev-parse", "HEAD")

    def test_new_checkout_fetches_only_the_pin_then_supports_normal_fast_forward(self):
        checkout = self.directory / "upstream"
        with patch.object(sync, "UPSTREAM_URL", self.origin.as_uri()):
            self.assertEqual(sync.checkout_upstream_revision(checkout, self.first), self.first)
        self.assertEqual(self.git(checkout, "remote", "get-url", "origin"), self.origin.as_uri())
        self.assertEqual(self.git(checkout, "rev-parse", "--abbrev-ref", "HEAD"), "HEAD")
        self.assertEqual(self.git(checkout, "rev-parse", "--is-shallow-repository"), "true")
        self.assertEqual((checkout / "tutorial.adoc").read_text(encoding="utf-8"), "first")
        self.git(checkout, "fetch", "origin", "main")
        self.git(checkout, "merge", "--ff-only", "FETCH_HEAD")
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), self.latest)

    def test_matching_pin_reuses_the_checkout_without_a_remote(self):
        with patch.object(sync, "UPSTREAM_URL", (self.directory / "missing").as_uri()):
            self.assertEqual(sync.checkout_upstream_revision(self.origin, self.latest), self.latest)

    def test_unavailable_pin_never_falls_back_to_main(self):
        checkout = self.directory / "upstream"
        with patch.object(sync, "UPSTREAM_URL", self.origin.as_uri()):
            with self.assertRaises(subprocess.CalledProcessError):
                sync.checkout_upstream_revision(checkout, "0" * 40)
        self.assertFalse((checkout / "tutorial.adoc").exists())

    def test_tracked_and_untracked_changes_are_preserved(self):
        source = self.origin / "tutorial.adoc"
        source.write_text("local edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires a clean worktree"):
            sync.checkout_upstream_revision(self.origin, self.first)
        self.assertEqual(source.read_text(encoding="utf-8"), "local edit")
        source.write_text("latest", encoding="utf-8")
        local = self.origin / "extra.adoc"
        local.write_text("untracked content", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires a clean worktree"):
            sync.checkout_upstream_revision(self.origin, self.latest)
        self.assertEqual(local.read_text(encoding="utf-8"), "untracked content")
        self.assertEqual(self.git(self.origin, "rev-parse", "HEAD"), self.latest)


class MirrorTests(unittest.TestCase):
    def test_navigation_retains_heading_only_entries_and_repeated_links(self):
        entries = [
            {"title": "Engine Architecture", "depth": 1},
            {"id": "setup", "title": "Setup", "depth": 2},
            {"id": "setup", "title": "Base Code", "depth": 3},
        ]
        key = sync.translation_key("Setup", {}, "glossary")
        navigation = sync.navigation_metadata(entries, {"setup"}, {key: "设置"}, "glossary")
        self.assertEqual([entry.get("id") for entry in navigation], [None, "setup", "setup"])
        self.assertEqual([entry["depth"] for entry in navigation], [1, 2, 3])
        self.assertEqual(navigation[1]["titleZh"], "设置")
        self.assertEqual(navigation[2]["titleZh"], "基础代码")
        self.assertNotIn("titleZh", navigation[0])

    def test_missing_navigation_target_becomes_a_heading_without_a_broken_link(self):
        entry = sync.navigation_metadata([{"id": "removed", "title": "Topic", "depth": 1}], set(), {}, "glossary")[0]
        self.assertEqual(entry, {"title": "Topic", "depth": 1})

    def test_local_chapter_link_preserves_anchor(self):
        result = sync.route_link("01_Instance.html#creation", "03/00_Base", {"03/01_Instance"})
        self.assertEqual(result, "/?page=03%2F01_Instance#creation")

    def test_absolute_root_chapter(self):
        self.assertEqual(sync.route_link("03/01_Instance.adoc", "00_Introduction", {"03/01_Instance"}), "/?page=03%2F01_Instance")

    def test_external_link_is_unchanged(self):
        target = "https://example.org/images/api.html"
        self.assertEqual(sync.route_link(target, "00_Introduction", set()), target)

    def test_assets_resolve(self):
        self.assertEqual(sync.route_link("../../../images/example.png", "a/b/c", set()), "/assets/images/example.png")
        self.assertEqual(sync.route_link("/attachments/Vulkan%20Test.pdf", "intro", set()), "/assets/attachments/Vulkan Test.pdf")

    def test_translation_preserves_code_and_provides_glossary(self):
        element = BeautifulSoup('<p>Create a <code>vk::raii::Device</code> and a swap chain with <a href="/?page=next">the next chapter</a>.</p>', "html.parser").p
        plain, tokens = sync.prepare_translation(element, {"swap chain": "交换链"})
        self.assertNotIn("vk::raii::Device", plain)
        restored = sync.restore_translation(plain.replace("Create a", "创建一个"), tokens)
        self.assertIn("<code>vk::raii::Device</code>", restored)
        self.assertIn('data-term="swap chain"', restored)
        self.assertIn('href="/?page=next"', restored)

    def test_missing_token_rejected(self):
        with self.assertRaises(ValueError):
            sync.restore_translation("translation omitted the API token", {"__VT00000__": "<code>vkCreateInstance</code>"})

    def test_term_only_headings_are_translated_without_google(self):
        heading = BeautifulSoup('<h2>Fragment shader</h2>', 'html.parser').h2
        plain, tokens = sync.prepare_translation(heading, {'fragment shader': '片段着色器'})
        translated = sync.local_term_translation(plain, tokens)
        self.assertIn('data-term="Fragment shader"', translated)
        self.assertIn('片段着色器', translated)

    def test_code_only_blocks_are_not_treated_as_translatable_terms(self):
        self.assertIsNone(sync.local_term_translation('__VT00000__', {'__VT00000__': '<code>vk::ShaderModule</code>'}))
        self.assertIsNone(sync.local_term_translation('Use __VT00000__', {'__VT00000__': '<span data-term="shader">着色器</span>'}))

    def test_google_marker_decoration_can_change_without_losing_identity(self):
        tokens = {"__VT00000__": "<a>", "__VT00001__": "</a>"}
        for translated in ("__ VT00000 __ VT00001_ 归属", "_ VT00000 _ 内容 __ VT00001 __", "＿vt０００００＿内容__VT00001__"):
            restored = sync.restore_translation(translated, tokens)
            self.assertIn("<a>", restored)
            self.assertIn("</a>", restored)
        with self.assertRaises(ValueError):
            sync.restore_translation("VT00000 内容 VT00000 VT00001", tokens)
        with self.assertRaises(ValueError):
            sync.restore_translation("VT00000 内容 VT00001 VT00009", tokens)

    def test_cache_key_includes_protected_api_and_link(self):
        base = "Use __VT00000__"
        first = sync.translation_key(base, {"__VT00000__": "<code>vkFoo</code>"}, "glossary")
        second = sync.translation_key(base, {"__VT00000__": "<code>vkBar</code>"}, "glossary")
        third = sync.translation_key(base, {"__VT00000__": '<a href="/?page=chapter">chapter</a>'}, "glossary")
        self.assertEqual(len({first, second, third}), 3)

    def test_batch_response_delimiters_cannot_shift_translations(self):
        with self.assertRaises(ValueError):
            sync.parse_google_batch("__VTSEG00000__\n第一条\n__VTEND__", 2)
        self.assertEqual(sync.parse_google_batch("__VTSEG00000__\n第一条\n__VTSEG00001__\n第二条\n__VTEND__", 2), ["第一条", "第二条"])
        with self.assertRaises(ValueError):
            sync.parse_google_batch("__VTSEG00001__\n第二条\n__VTSEG00000__\n第一条\n__VTEND__", 2)

    def test_provider_namespace_prevents_edge_cache_reuse(self):
        original = "Select the device."
        google = sync.translation_key(original, {}, "glossary", provider="google")
        edge = sync.translation_key(original, {}, "glossary", provider="edge")
        self.assertNotEqual(google, edge)

    def test_batches_respect_item_and_character_limits(self):
        items = [(str(index), {"text": "x" * 1000}) for index in range(25)]
        batches = list(sync.translation_batches(items, max_items=20, max_characters=9500))
        self.assertEqual([len(batch) for batch in batches], [9, 9, 7])
        small_items = [(str(index), {"text": "short"}) for index in range(35)]
        self.assertEqual([len(batch) for batch in sync.translation_batches(small_items)], [32, 3])

    def test_table_cell_remains_visible_in_chinese(self):
        soup = BeautifulSoup('<table><tr><td>English text</td><th>Heading</th></tr></table><dl><dt>Definition</dt></dl>', "html.parser")
        for cell in soup.select("td,th,dt"):
            pair = sync.wrap_bilingual_pair(soup, cell)
            self.assertNotIn("vt-en", cell.get("class", []))
            self.assertIn("vt-en", pair.find(recursive=False).get("class", []))
            self.assertEqual(pair.parent, cell)

    def test_soft_linebreaks_are_normalized_outside_code(self):
        soup = BeautifulSoup('<p>Choose a\nphysical device\nthen use <code>line1\nline2</code>.</p>', "html.parser")
        text, tokens = sync.prepare_translation(soup.p, {})
        self.assertNotIn("\n", text)
        self.assertIn("Choose a physical device then use", text)
        self.assertIn("line1\nline2", "".join(tokens.values()))

    def test_google_rpc_maps_reordered_results_by_index(self):
        def record(index, text):
            data = [None, [[[None, None, None, None, None, [[text]]]]]]
            return ["wrb.fr", "MkEWBc", json.dumps(data), None, None, None, str(index)]
        payload = ")]}'\n\n100\n" + json.dumps([record(1, "第二段"), record(0, "第一段")])
        self.assertEqual(sync.parse_google_rpc(payload, 2), ["第一段", "第二段"])
        self.assertEqual(sync.parse_google_rpc(json.dumps([record(0, "第一段")]), 2), ["第一段", None])
        with self.assertRaises(ValueError):
            sync.parse_google_rpc(json.dumps([record(0, "第一段"), record(0, "重复")]), 2)

    def test_google_rpc_bad_item_preserves_other_indexed_results(self):
        def record(index, segments):
            data = [None, [[[None, None, None, None, None, segments]]]]
            return ["wrb.fr", "MkEWBc", json.dumps(data), None, None, None, str(index)]
        payload = json.dumps([record(2, [["第三段"]]), record(1, None), record(0, [["第一段"]])])
        self.assertEqual(sync.parse_google_rpc(payload, 3), ["第一段", None, "第三段"])
        with self.assertRaises(ValueError):
            sync.parse_google_rpc(json.dumps([record(0, None)]), 1)

    def test_unavailable_rpc_item_does_not_discard_valid_translations(self):
        translator = sync.GoogleTranslator(delay=0)
        translator.gtx_retry_disabled = True
        translator.translate_many = Mock(return_value=[None, "第二段"])
        translator.translate_rpc = Mock(side_effect=ValueError("Item remains unavailable"))
        translator.translate = Mock()
        result = sync.translate_validated_batch(translator, [("missing", {"text": "First", "tokens": {}}), ("valid", {"text": "Second", "tokens": {}})])
        self.assertIsNone(result[0][1])
        self.assertIsNotNone(result[0][2])
        self.assertEqual(result[1], ("valid", "第二段", None))
        translator.translate.assert_not_called()

    def test_single_gtx_rate_limit_keeps_other_rpc_results_and_future_batches(self):
        translator = sync.GoogleTranslator(delay=0)
        translator.translate_many = Mock(return_value=["缺失标记", "第二段", "也缺失标记", "第四段"])
        translator.translate_rpc = Mock(return_value=["仍然缺失标记"])
        translator.translate = Mock(side_effect=sync.TranslationRateLimited("GTX blocked"))
        batch = [
            ("first", {"text": "First __VT00000__", "tokens": {"__VT00000__": "<code>vkFoo</code>"}}),
            ("second", {"text": "Second", "tokens": {}}),
            ("third", {"text": "Third __VT00000__", "tokens": {"__VT00000__": "<code>vkBar</code>"}}),
            ("fourth", {"text": "Fourth", "tokens": {}}),
        ]
        result = sync.translate_validated_batch(translator, batch)
        self.assertEqual(result[1], ("second", "第二段", None))
        self.assertEqual(result[3], ("fourth", "第四段", None))
        self.assertIsNotNone(result[0][2])
        self.assertIsNotNone(result[2][2])
        self.assertTrue(translator.gtx_retry_disabled)
        translator.translate.assert_called_once()
        translator.translate_many.return_value = ["后续成功"]
        self.assertEqual(sync.translate_validated_batch(translator, [("next", {"text": "Next", "tokens": {}})]), [("next", "后续成功", None)])

    def test_independent_rpc_repairs_item_without_gtx(self):
        translator = sync.GoogleTranslator(delay=0)
        translator.translate_many = Mock(return_value=["标记缺失"])
        translator.translate_rpc = Mock(return_value=["使用 __VT00000__"])
        translator.translate = Mock()
        result = sync.translate_validated_batch(translator, [("item", {"text": "Use __VT00000__", "tokens": {"__VT00000__": "<code>vkFoo</code>"}})])
        self.assertEqual(result, [("item", "使用 <code>vkFoo</code>", None)])
        translator.translate.assert_not_called()

    def test_batch_stops_only_when_main_rpc_and_gtx_are_unavailable(self):
        translator = sync.GoogleTranslator(delay=0)
        translator.gtx_retry_disabled = True
        translator.translate_rpc = Mock(side_effect=sync.HTTPError("https://translate.google.com/", 429, "Rate limited", {}, None))
        with self.assertRaises(sync.TranslationRateLimited):
            translator.translate_many(["A paragraph"])

    def test_rpc_parse_error_is_not_classified_as_rate_limit(self):
        translator = sync.GoogleTranslator(delay=0)
        translator.gtx_retry_disabled = True
        translator.translate_rpc = Mock(side_effect=ValueError("Malformed RPC item"))
        with self.assertRaises(ValueError):
            translator.translate_many(["A paragraph"])

    def test_curated_titles_are_case_insensitive(self):
        self.assertEqual(sync.SEED_CASEFOLD["SWAP CHAIN RECREATION".casefold()], "重建交换链")
        self.assertEqual(sync.SEED_CASEFOLD["Frames In Flight".casefold()], "并行帧")


if __name__ == "__main__":
    unittest.main()
