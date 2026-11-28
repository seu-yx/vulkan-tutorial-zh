#!/usr/bin/env python3
"""Find untranslated emphasis and repeated English terms in the generated reader text."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup, NavigableString

if __package__:
    from .term_views import project_term_views
else:
    from term_views import project_term_views

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


def repeated_term_phrases(view):
    """Find adjacent copies of a visible term, with at least one copy grounded in a marker."""
    annotated = defaultdict(set)
    protected = []
    offset = 0
    for run in view['runs']:
        value = run['on']
        end = offset + len(value)
        if run['term']:
            # The reader can add a boundary space on either side of an English term.
            annotated[run['term']].add((offset + len(value) - len(value.lstrip()),
                                        offset + len(value.rstrip())))
        elif run['protected'] and value:
            protected.append((offset, end))
        offset = end

    visible = view['on']
    hits = {}
    for label, spans in annotated.items():
        name = r'\s+'.join(map(re.escape, label.split()))
        # A lookahead also checks the last two occurrences in a run of three.
        pattern = (rf'(?<![a-z0-9_])(?=(?P<phrase>(?P<first>{name})\s+'
                   rf'(?P<second>{name}))(?![a-z0-9_]))')
        for match in re.finditer(pattern, visible, re.IGNORECASE):
            if match.span('first') not in spans and match.span('second') not in spans:
                continue
            start, end = match.span('phrase')
            if any(start < right and left < end for left, right in protected):
                continue
            hits[start] = match.group('phrase')
    return list(dict.fromkeys(hits[start] for start in sorted(hits)))


def heading_location(english, pair, fallback):
    heading = english if english.name in HEADINGS else pair.find_previous(HEADINGS, class_='vt-en')
    return {'heading': heading.get_text(' ', strip=True) if heading else fallback,
            'anchor': heading.get('id') if heading else None}


def scan_projected_terms(blocks, locations, *, trim):
    findings = []
    for view, location in zip(project_term_views(blocks, trim=trim), locations, strict=True):
        phrases = repeated_term_phrases(view)
        if phrases:
            findings.append({**location, 'chinese': view['off'], 'englishTerms': view['on'],
                             'phrases': phrases})
    return findings


def audit(data):
    catalog = json.loads((data / 'catalog.json').read_text(encoding='utf-8'))
    pages = catalog['pages']
    bilingual = 0
    findings = []
    repeated = []
    title_blocks, title_locations = [], []
    for metadata in pages:
        page_id = metadata['id']
        page = json.loads((data / 'pages' / (page_id + '.json')).read_text(encoding='utf-8'))
        soup = BeautifulSoup(page['html'], 'html.parser')
        title = page.get('title', metadata.get('title', page_id))
        title_html = page.get('titleZhHtml') or metadata.get('titleZhHtml')
        if title_html:
            title_blocks.append(BeautifulSoup(title_html, 'html.parser'))
            title_locations.append({'scope': 'pageTitle', 'page': page_id, 'heading': title,
                                    'anchor': None, 'english': title})
        blocks, locations = [], []
        for pair_number, pair in enumerate(soup.select('.vt-pair'), 1):
            english = pair.find(class_='vt-en', recursive=False)
            chinese = pair.find(class_='vt-zh', recursive=False)
            if english is None or chinese is None:
                continue
            bilingual += 1
            leaked = untranslated_emphasis(english, chinese)
            if leaked:
                findings.append({
                    'page': page_id, **heading_location(english, pair, title), 'words': leaked,
                    'english': english.get_text(' ', strip=True)[:480],
                    'chinese': chinese.get_text(' ', strip=True)[:480],
                })
            if chinese.select_one('.vt-term'):
                blocks.append(chinese)
                locations.append({'scope': 'body', 'page': page_id, 'pair': pair_number,
                                  **heading_location(english, pair, title),
                                  'english': english.get_text(' ', strip=True)})
        if blocks:
            repeated.extend(scan_projected_terms(blocks, locations, trim=True))

    for index, entry in enumerate(catalog.get('navigation', [])):
        if entry.get('titleZhHtml'):
            title_blocks.append(BeautifulSoup(entry['titleZhHtml'], 'html.parser'))
            title_locations.append({'scope': 'navigation', 'page': entry.get('id'),
                                    'navigationIndex': index, 'heading': entry['title'],
                                    'anchor': None, 'english': entry['title']})
    if title_blocks:
        repeated.extend(scan_projected_terms(title_blocks, title_locations, trim=False))
    return {
        'pages': len(pages),
        'bilingualBlocks': bilingual,
        'affectedPages': len({item['page'] for item in findings}),
        'findings': findings,
        'repeatedTerms': repeated,
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
          f"{report['affectedPages']} pages and repeated English terms in "
          f"{len(report['repeatedTerms'])} reader locations. Report: {args.output}")


if __name__ == '__main__':
    main()
