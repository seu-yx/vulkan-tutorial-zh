"""Offline proofreading must see the same term text as the reader switch."""

import unittest

from bs4 import BeautifulSoup

from scripts.term_views import project_term_views


def fragment(markup):
    return BeautifulSoup(markup, 'html.parser')


class TermViewTests(unittest.TestCase):
    def test_both_views_and_marker_provenance(self):
        content = fragment(
            '使用 <span class="vt-term" data-english="G-buffer" data-term="buffer">几何缓冲区</span>'
            ' （G-buffer）和<a href="/q"><em class="vt-term" data-term="queue">队列</em></a>。'
            '<code><i class="vt-term" data-term="wrong">标识</i></code><!-- no text -->'
        )
        initial = str(content)
        view, = project_term_views([content])
        self.assertEqual(view['off'], '使用几何缓冲区（G-buffer）和队列。标识')
        self.assertEqual(view['on'], '使用 G-buffer 和 queue。标识')
        self.assertEqual([r['term'] for r in view['runs'] if r['term']], ['G-buffer', 'queue'])
        self.assertEqual([r['text'] for r in view['runs'] if r['protected']], ['队列', '标识'])
        self.assertEqual(view['on'], ''.join(r['on'] for r in view['runs']))
        self.assertEqual(str(content), initial)

    def test_duplicates_remain_visible_but_protected_glosses_survive(self):
        duplicate = fragment('测试<span class="vt-term" title="mipmap">多级渐远纹理</span> mipmap')
        protected = fragment('看<span class="vt-term" data-term="queue">队列</span>'
                             '<a href="#">（queue）</a><code>vk::Queue</code>')
        plain = fragment('普通 <b>正文</b>')
        first, second, third = project_term_views([duplicate, protected, plain])
        self.assertEqual(first['on'], '测试 mipmap mipmap')
        self.assertEqual(second['on'], '看 queue（queue）vk::Queue')
        self.assertEqual(third['off'], third['on'])
        self.assertEqual(third['on'], '普通 正文')

    def test_only_direct_body_siblings_get_padding_trimmed(self):
        content = fragment('见 <span class="vt-term" data-term="queue family">队列族</span> 说明')
        nested = fragment('文 <em><span class="vt-term" data-term="X">词</span></em> 字')
        body, nested_body = project_term_views([content, nested])
        title, = project_term_views([content], trim=False)
        self.assertEqual(body['off'], '见队列族说明')
        self.assertEqual(title['off'], '见 队列族 说明')
        self.assertEqual(body['on'], title['on'])
        self.assertEqual(nested_body['off'], '文 词 字')

    def test_every_occurrence_and_adjacent_emphasis(self):
        content = fragment('连<span class="vt-term" data-term="A">甲</span>'
                           '<em><span class="vt-term" data-term="A">甲</span></em>丙')
        view, = project_term_views([content])
        self.assertEqual(view['on'], '连 A A 丙')
        self.assertEqual([r['term'] for r in view['runs'] if r['term']], ['A', 'A'])


if __name__ == '__main__':
    unittest.main()
