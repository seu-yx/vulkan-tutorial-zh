"""Display-only terminology must preserve source, cached markup and identifiers."""
from pathlib import Path
import sys
import unittest

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from terminology import TermAnnotator, annotate_terms


class TerminologyTests(unittest.TestCase):
    def pair(self, english, chinese):
        soup = BeautifulSoup(f'<div><p class="vt-en">{english}</p><p class="vt-zh">{chinese}</p></div>', "html.parser")
        return soup, soup.select_one(".vt-en"), soup.select_one(".vt-zh")

    def test_configuration_requires_a_terms_list(self):
        with self.assertRaisesRegex(ValueError, "contain a terms list"):
            TermAnnotator({"description": "Missing terms"})
        for value in (None, {}, "surface", 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "terms must be a list"):
                TermAnnotator({"terms": value})
        self.assertEqual(TermAnnotator({"terms": [], "description": "Empty is supported", "$schema": "./terminology.schema.json"}).terms, {})

    def test_duplicate_canonical_terms_are_case_and_whitespace_insensitive(self):
        with self.assertRaisesRegex(ValueError, r"terms\[1\].*duplicate canonical English term"):
            TermAnnotator([
                {"english": "Window Surface", "chinese": "窗口表面"},
                {"english": " window\n  surface ", "chinese": "窗口表面"},
            ])

    def test_unknown_entry_and_context_fields_are_rejected(self):
        for extra in ({"normlize": True}, {"englishAliases": ["surfaces"]}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, r"terms\[0\].*unknown terminology fields"):
                TermAnnotator([{"english": "surface", "chinese": "表面", **extra}])
        with self.assertRaisesRegex(ValueError, r"terms\[0\]\.context.*unknown fields: requiredAny"):
            TermAnnotator([{"english": "surface", "chinese": "表面", "context": {"requiredAny": ["window"]}}])

    def test_normalize_requires_an_actual_boolean(self):
        for value in (1, 0, "true", None, []):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, r"normalize must be a boolean"):
                TermAnnotator([{"english": "surface", "chinese": "表面", "normalize": value}])
        for value in (True, False):
            self.assertEqual(TermAnnotator([{"english": "surface", "chinese": "表面", "normalize": value}]).terms["surface"]["normalize"], value)

    def test_context_fields_require_literal_strings_or_string_lists(self):
        for name in ("requireAny", "excludeAny"):
            for value in (None, True, 1, {}, ["window", 1], " ", [""]):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name + " must be a nonempty string or a list"):
                    TermAnnotator([{"english": "surface", "chinese": "表面", "context": {name: value}}])
        for context in (None, "window", ["window"]):
            with self.subTest(context=context), self.assertRaisesRegex(ValueError, r"context must be an object"):
                TermAnnotator([{"english": "surface", "chinese": "表面", "context": context}])
        for name in ("includeContext", "excludeContext"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name + " must be"):
                TermAnnotator([{"english": "surface", "chinese": "表面", name: [2]}])

    def test_valid_context_shortcuts_and_object_guards_work(self):
        for guard in ({"includeContext": "window", "excludeContext": ["geometry"]}, {"context": {"requireAny": ["window"], "excludeAny": "geometry"}}):
            annotator = TermAnnotator([{"english": "surface", "chinese": "表面", **guard}])
            _, english, chinese = self.pair("A window surface", "窗口表面")
            self.assertEqual(annotator.annotate(english, chinese)["added"], 1)
            _, english, chinese = self.pair("A geometry surface", "几何表面")
            self.assertEqual(annotator.annotate(english, chinese)["added"], 0)

    def test_exact_aliases_only_activate_for_the_entire_source_phrase(self):
        annotator = TermAnnotator([{"english": "presentation", "chinese": "呈现", "aliases": ["演示"], "exactAliases": ["介绍"], "variants": ["presentations"], "normalize": True}])
        for source in (" Presentation ", "PRESENTATIONS", "<em>Presentation</em>"):
            with self.subTest(source=source):
                _, english, chinese = self.pair(source, "介绍")
                self.assertEqual(annotator.annotate(english, chinese)["added"], 1)
                self.assertEqual(chinese.get_text(), "呈现")
        _, english, chinese = self.pair("This introduction covers presentation", "本介绍涵盖呈现")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 1)
        self.assertEqual(chinese.get_text(), "本介绍涵盖呈现")
        self.assertEqual(chinese.span.get_text(), "呈现")
        for source in ("Presentation example", "Presentation https://example.test/", "Presentation <code>vkQueuePresentKHR</code>"):
            with self.subTest(source=source):
                _, english, chinese = self.pair(source, "介绍")
                self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
                self.assertEqual(chinese.get_text(), "介绍")

    def test_exact_aliases_require_nonempty_string_list(self):
        for aliases in (None, "介绍", [""], [1]):
            with self.subTest(aliases=aliases), self.assertRaisesRegex(ValueError, "exactAliases must be lists"):
                TermAnnotator([{"english": "presentation", "chinese": "呈现", "exactAliases": aliases}])

    def test_visible_urls_and_email_addresses_are_neither_source_terms_nor_targets(self):
        annotator = TermAnnotator([{"english": "presentation", "chinese": "呈现", "normalize": True}])
        url = "https://s2026.conference-schedule.org/presentation/?id=123"
        _, english, chinese = self.pair(url, url)
        before = str(chinese)
        self.assertEqual(annotator.annotate(english, chinese)["source"], 0)
        self.assertEqual(str(chinese), before)
        _, english, chinese = self.pair(
            f'Presentation: {url} or presentation@example.test',
            f'介绍：<a href="{url}">{url}</a> presentation@example.test。<a href="{url}">presentation</a>',
        )
        hrefs = [link["href"] for link in chinese.select("a")]
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["source"], 1)
        self.assertEqual(result["added"], 1)
        self.assertEqual(chinese.select("a")[0].get_text(), url)
        self.assertEqual(chinese.select("a")[1].span.get_text(), "呈现")
        self.assertEqual([link["href"] for link in chinese.select("a")], hrefs)
        self.assertIn("presentation@example.test", chinese.get_text())

    def test_source_grounding_normalization_and_idempotence(self):
        annotator = TermAnnotator({"terms": [{"english": "presentation", "chinese": "呈现", "aliases": ["演示"], "normalize": True}]})
        _, english, chinese = self.pair("Rendering and presentation", "渲染和演示")
        before = str(english)
        result = annotate_terms(english, chinese, annotator)
        self.assertEqual(str(english), before)
        self.assertEqual(chinese.get_text(), "渲染和呈现")
        self.assertEqual(chinese.span["title"], "presentation")
        self.assertEqual(result["normalized"], 1)
        self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
        _, english, chinese = self.pair("Demonstrate a rendering example", "演示渲染示例")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
        self.assertEqual(chinese.get_text(), "演示渲染示例")

    def test_longest_phrases_and_plural_case_whitespace(self):
        annotator = TermAnnotator([
            {"english": "surface", "chinese": "表面", "variants": ["surfaces"]},
            {"english": "window surface", "chinese": "窗口表面", "variants": ["window surfaces"]},
        ])
        _, english, chinese = self.pair("WINDOW <em>surfaces</em> and surfaces", "窗口表面和表面")
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["source"], 2)
        self.assertEqual([span["data-term"] for span in chinese.select(".vt-term")], ["window surface", "surface"])
        self.assertEqual(chinese.get_text(), "窗口表面和表面")

    def test_code_api_links_and_existing_annotations_are_preserved(self):
        annotator = TermAnnotator([{"english": "surface", "chinese": "表面", "variants": ["surfaces"]}])
        _, english, chinese = self.pair(
            'Use a surface and <code>surface</code>, vk::Surface, VK_SURFACE and surfaces.',
            '<code>表面 Surface</code> <a href="/surface" title="link surface"><em>表面</em></a> '
            '<span class="vt-term" data-term="surface" title="surface">表面</span> vk::Surface VK_SURFACE',
        )
        before_english, before_code = str(english), str(chinese.code)
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["source"], 2)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["existing"], 1)
        self.assertEqual(str(english), before_english)
        self.assertEqual(str(chinese.code), before_code)
        self.assertEqual(chinese.a["href"], "/surface")
        self.assertEqual(chinese.a["title"], "link surface")
        self.assertEqual(chinese.em.span["data-term"], "surface")
        self.assertIn("vk::Surface VK_SURFACE", chinese.get_text())
        self.assertFalse(chinese.select(".vt-term .vt-term"))

    def test_context_guard_avoids_ambiguous_demo_translation(self):
        annotator = TermAnnotator([{"english": "presentation", "chinese": "呈现", "aliases": ["演示"], "normalize": True, "excludeContext": ["demo", "demonstration"]}])
        _, english, chinese = self.pair("The demo shows presentation", "演示展示了演示")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
        _, english, chinese = self.pair("A democratic presentation", "演示")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 1, "Context exclusions use words, not substrings")

    def test_source_counts_bound_alias_replacement(self):
        annotator = TermAnnotator([{"english": "presentation", "chinese": "呈现", "aliases": ["演示"], "normalize": True}])
        _, english, chinese = self.pair("A presentation", "演示和演示")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 1)
        self.assertEqual(chinese.get_text(), "呈现和演示")

    def test_untranslated_words_have_boundaries_and_opt_in_normalization(self):
        annotator = TermAnnotator([{"english": "surface", "chinese": "表面", "variants": ["surfaces"], "normalize": True}])
        _, english, chinese = self.pair("Surface and surfaces", "Surface, surfaces, resurfaced, SurfaceKHR")
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["added"], 2)
        self.assertEqual(chinese.get_text(), "表面, 表面, resurfaced, SurfaceKHR")

    def test_require_context_and_ambiguous_shared_aliases(self):
        annotator = TermAnnotator([
            {"english": "instance", "chinese": "实例", "context": {"requireAny": ["Vulkan"]}},
            {"english": "object", "chinese": "实例"},
        ])
        _, english, chinese = self.pair("An instance of a function", "实例")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
        _, english, chinese = self.pair("A Vulkan instance and an object", "实例和实例")
        self.assertEqual(annotator.annotate(english, chinese)["added"], 0)

    def test_split_chinese_phrase_does_not_destroy_inline_markup(self):
        annotator = TermAnnotator([{"english": "window surface", "chinese": "窗口表面"}])
        _, english, chinese = self.pair("Window surface", "窗口<em>表面</em>")
        before = str(chinese)
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(str(chinese), before)

    def test_long_phrase_can_merge_old_short_annotations_without_nesting(self):
        annotator = TermAnnotator([
            {"english": "texture", "chinese": "纹理"},
            {"english": "texture coordinates", "chinese": "纹理坐标", "normalize": True},
        ])
        _, english, chinese = self.pair(
            "Use texture coordinates and a texture.",
            '使用 <span class="vt-term" data-term="texture" title="texture">纹理</span> 坐标和纹理。',
        )
        result = annotator.annotate(english, chinese)
        self.assertEqual([span["data-term"] for span in chinese.select(".vt-term")], ["texture coordinates", "texture"])
        self.assertEqual(chinese.get_text(), "使用 纹理坐标和纹理。")
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["unmatched"], 0)
        self.assertFalse(chinese.select(".vt-term .vt-term"))

    def test_split_merge_preserves_unmatched_term_links_and_emphasis(self):
        annotator = TermAnnotator([
            {"english": "shader", "chinese": "着色器"},
            {"english": "shader invocation", "chinese": "着色器调用"},
        ])
        _, english, chinese = self.pair(
            "One shader invocation and one shader.",
            '<a href="/target"><span class="vt-term" data-term="shader" title="shader">着色器</span> 调用</a> '
            '<span class="vt-term" data-term="shader" title="shader">着色器</span> <em>保留</em>',
        )
        last_term = chinese.select(".vt-term")[-1]
        result = annotator.annotate(english, chinese)
        self.assertEqual(chinese.a["href"], "/target")
        self.assertEqual(chinese.a.span["data-term"], "shader invocation")
        self.assertIs(chinese.select(".vt-term")[-1], last_term)
        self.assertEqual(chinese.em.get_text(), "保留")
        self.assertEqual(result["unmatched"], 0)

    def test_partial_old_span_and_bookmarks_cannot_be_removed(self):
        annotator = TermAnnotator([{"english": "texture coordinates", "chinese": "纹理坐标"}])
        for content in [
            '<span class="vt-term" data-term="texture" title="texture">纹理图像</span>坐标',
            '<span class="vt-term" data-term="texture" title="texture" id="bookmark">纹理</span>坐标',
            '<span class="vt-term" data-term="texture" title="texture">纹理</span><em>坐标</em>',
        ]:
            _, english, chinese = self.pair("Texture coordinates", content)
            before = str(chinese)
            self.assertEqual(annotator.annotate(english, chinese)["added"], 0)
            self.assertEqual(str(chinese), before)

    def test_inactive_long_alias_cannot_swallow_an_active_shorter_term(self):
        annotator = TermAnnotator([
            {"english": "surface", "chinese": "表面"},
            {"english": "window surface", "chinese": "窗口表面"},
        ])
        _, english, chinese = self.pair("A surface", "窗口表面")
        result = annotator.annotate(english, chinese)
        self.assertEqual(result["added"], 1)
        self.assertEqual(chinese.span.get_text(), "表面")
        self.assertEqual(chinese.span["data-term"], "surface")
        self.assertEqual(chinese.get_text(), "窗口表面")

    def test_google_markdown_emphasis_does_not_hide_an_english_term(self):
        annotator = TermAnnotator([{"english": "inference", "chinese": "推理"}])
        _, english, chinese = self.pair("Inference", "使用 _inference_。")
        result = annotator.annotate(english, chinese)
        self.assertEqual(result['added'], 1)
        self.assertEqual(chinese.span['data-term'], 'inference')
        self.assertEqual(chinese.get_text(), '使用 _inference_。')

    def test_markdown_emphasis_support_does_not_match_identifiers(self):
        annotator = TermAnnotator([{"english": "image", "chinese": "图像"}])
        _, english, chinese = self.pair("An image", "image_index foo_image_bar")
        before = str(chinese)
        self.assertEqual(annotator.annotate(english, chinese)['added'], 0)
        self.assertEqual(str(chinese), before)


if __name__ == "__main__":
    unittest.main()
