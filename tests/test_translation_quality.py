import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bs4 import BeautifulSoup

from scripts.audit_translation_quality import audit, repeated_term_phrases, untranslated_emphasis
from scripts.term_views import project_term_views


class TranslationQualityTests(unittest.TestCase):
    def check_pair(self, english, chinese):
        soup = BeautifulSoup(f'<div class="vt-en">{english}</div><div class="vt-zh">{chinese}</div>', 'html.parser')
        return untranslated_emphasis(soup.select_one('.vt-en'), soup.select_one('.vt-zh'))

    def test_detects_untranslated_emphasis_in_dynamic_state(self):
        self.assertEqual(self.check_pair(
            'While <strong>most</strong> of the pipeline state needs to be baked in, some state <strong>can</strong> be changed.',
            '虽然管线状态的 <strong>most</strong> 需要烘焙，但部分状态 <strong>can</strong> 更改。',
        ), ['most', 'can'])

    def test_ignores_protected_and_intentional_english(self):
        english = 'Use <strong>can</strong>, <em>can</em>, <strong>VK_SUCCESS</strong>, <strong>CAN</strong> and <strong>Vulkan</strong>.'
        for chinese in (
            '状态 <strong><code>can</code></strong> 可以更改。',
            '状态 <a href="#ref"><strong>can</strong></a> 可以更改。',
            '状态 <strong><span class="vt-term">can</span></strong> 可以更改。',
            '状态 <strong class="vt-term" data-term="can">can</strong> 可以更改。',
            '保留 <strong>VK_SUCCESS</strong>、<strong>CAN</strong> 和 <strong>Vulkan</strong>。',
            '保留 <strong>not</strong>。',
            '<strong>can</strong> change.',
        ):
            with self.subTest(chinese=chinese):
                self.assertEqual(self.check_pair(english, chinese), [])

    def test_repeated_terms_follow_the_reader_and_respect_inline_boundaries(self):
        term = '<span class="vt-term" data-english="mipmap">多级纹理</span>'
        compound = '<span class="vt-term" data-english="command buffer">命令缓冲区</span>'
        examples = [
            (f'{term} <em>Mipmap</em>。', ['mipmap Mipmap']),
            (f'<em>mipmap</em> {term}', ['mipmap mipmap']),
            (f'{term} {term}', ['mipmap mipmap']),
            (f'{compound} command buffer', ['command buffer command buffer']),
            (f'{term}（mipmap）', []),  # The reader hides the redundant gloss.
            (f'{term} <code>mipmap</code>', []),
            (f'{term} <a href="mipmap.txt">mipmap</a>', []),
            (f'{term} mipmapLevel', []),
            (f'texture texture 与 {term}', []),
            ('<code>' + term + '</code> mipmap', []),
        ]
        blocks = [BeautifulSoup(markup, 'html.parser') for markup, _ in examples]
        for (markup, expected), view in zip(examples, project_term_views(blocks), strict=True):
            with self.subTest(markup=markup):
                self.assertEqual(repeated_term_phrases(view), expected)

    def test_flags_repeated_terms_in_read_only_body_titles_and_navigation(self):
        term = '<span class="vt-term" data-english="mipmap">多级纹理</span>'
        markup = f'{term} mipmap'
        page = {'id': 'example', 'title': 'Mipmaps', 'titleZhHtml': markup, 'html': (
            '<div class="vt-pair"><h2 id="levels" class="vt-en">Levels</h2>'
            '<h2 class="vt-zh">层级</h2></div>'
            '<div class="vt-pair"><p class="vt-en">Create a mipmap.</p>'
            f'<p class="vt-zh" data-vt-reviewed="true">创建{markup}。</p></div>'
        )}
        with TemporaryDirectory() as directory:
            data = Path(directory)
            (data / 'pages').mkdir()
            (data / 'pages/example.json').write_text(json.dumps(page), encoding='utf-8')
            catalog = {'pages': [{'id': 'example', 'title': 'Mipmaps'}],
                       'navigation': [{'title': 'Mipmaps group', 'titleZhHtml': markup}]}
            (data / 'catalog.json').write_text(json.dumps(catalog), encoding='utf-8')
            report = audit(data)

        self.assertEqual(report['findings'], [])
        body, title, nav = report['repeatedTerms']
        self.assertEqual(body, {
            'scope': 'body', 'page': 'example', 'heading': 'Levels', 'anchor': 'levels',
            'pair': 2, 'english': 'Create a mipmap.', 'chinese': '创建多级纹理 mipmap。',
            'englishTerms': '创建 mipmap mipmap。', 'phrases': ['mipmap mipmap'],
        })
        self.assertEqual((title['scope'], title['english']), ('pageTitle', 'Mipmaps'))
        self.assertEqual((nav['scope'], nav['navigationIndex'], nav['page']), ('navigation', 0, None))
        self.assertEqual(nav['phrases'], ['mipmap mipmap'])

    def test_report_includes_source_heading_and_anchor(self):
        with TemporaryDirectory() as directory:
            data = Path(directory)
            pages = [{'id': 'example', 'title': 'Example'}]
            (data / 'catalog.json').write_text(json.dumps({'pages': pages}), encoding='utf-8')
            (data / 'pages').mkdir()
            page = {'html': (
                '<div class="vt-pair"><h2 id="_dynamic_state" class="vt-en">Dynamic state</h2>'
                '<h2 class="vt-zh">动态状态</h2></div>'
                '<div class="vt-pair"><p class="vt-en">State <em>can</em> change.</p>'
                '<p class="vt-zh">状态 <em>can</em> 更改。</p></div>'
            )}
            (data / 'pages/example.json').write_text(json.dumps(page, ensure_ascii=False), encoding='utf-8')

            result = audit(data)

        self.assertEqual((result['pages'], result['bilingualBlocks'], result['affectedPages']), (1, 2, 1))
        self.assertEqual(result['findings'], [{
            'page': 'example', 'heading': 'Dynamic state', 'anchor': '_dynamic_state',
            'words': ['can'], 'english': 'State can change.', 'chinese': '状态 can 更改。',
        }])


if __name__ == '__main__':
    unittest.main()
