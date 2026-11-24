#!/usr/bin/env python3
"""Find untranslated English emphasis in generated Chinese prose."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff]")
HEADINGS = ('h1', 'h2', 'h3', 'h4', 'h5', 'h6')
EMPHASIS = ('strong', 'em')
FUNCTION_WORDS = {
    'all', 'always', 'both', 'can', 'cannot', 'could', 'does', 'may', 'might',
    'most', 'must', 'neither', 'never', 'no', 'not', 'only', 'should', 'some',
    'will', 'would',
}


def emphasized_words(block):
    for node in block.find_all(EMPHASIS, recursive=False):
        if not node.contents or node.has_attr('data-term') or 'vt-term' in node.get('class', []):
            continue
        # Restrict the check to prose directly inside the emphasis tag. Nested
        # terms, code and links can contain intentionally untranslated words.
        if len(node.contents) == 1 and type(node.contents[0]) is NavigableString:
            word = node.contents[0].strip()
            if word in FUNCTION_WORDS:
                yield node.name, word


def untranslated_emphasis(english, chinese):
    if not any(type(node) is NavigableString and HAN.search(node) for node in chinese.contents):
        return []
    source = set(emphasized_words(english))
    return [word for kind, word in emphasized_words(chinese) if (kind, word) in source]


def audit(data):
    pages = json.loads((data / 'catalog.json').read_text(encoding='utf-8'))['pages']
    bilingual = 0
    findings = []
    for metadata in pages:
        page_id = metadata['id']
        page = json.loads((data / 'pages' / (page_id + '.json')).read_text(encoding='utf-8'))
        soup = BeautifulSoup(page['html'], 'html.parser')
        for pair in soup.select('.vt-pair'):
            english = pair.find(class_='vt-en', recursive=False)
            chinese = pair.find(class_='vt-zh', recursive=False)
            if english is None or chinese is None:
                continue
            bilingual += 1
            leaked = untranslated_emphasis(english, chinese)
            if not leaked:
                continue
            heading = english if english.name in HEADINGS else pair.find_previous(HEADINGS, class_='vt-en')
            findings.append({
                'page': page_id,
                'heading': heading.get_text(' ', strip=True) if heading else metadata.get('title', page_id),
                'anchor': heading.get('id') if heading else None,
                'words': leaked,
                'english': english.get_text(' ', strip=True)[:480],
                'chinese': chinese.get_text(' ', strip=True)[:480],
            })
    return {
        'pages': len(pages),
        'bilingualBlocks': bilingual,
        'affectedPages': len({item['page'] for item in findings}),
        'findings': findings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'public/data')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/translation-quality.json')
    args = parser.parse_args()
    report = audit(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Audited {report['pages']} pages and {report['bilingualBlocks']} bilingual blocks. "
          f"Found untranslated emphasis in {len(report['findings'])} blocks across "
          f"{report['affectedPages']} pages. Report: {args.output}")


if __name__ == '__main__':
    main()
