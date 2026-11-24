import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bs4 import BeautifulSoup

from scripts.audit_translation_quality import audit, untranslated_emphasis


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
