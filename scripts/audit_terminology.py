#!/usr/bin/env python3
"""Audit every generated bilingual page against the extensible term configuration."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path

from bs4 import BeautifulSoup

if __package__:
    from .terminology import TermAnnotator
else:
    from terminology import TermAnnotator

ROOT = Path(__file__).resolve().parents[1]


def audit(data, config):
    annotator = TermAnnotator(config)
    catalog = json.loads((data / 'catalog.json').read_text(encoding='utf-8'))
    totals = Counter()
    terms = defaultdict(Counter)
    examples = defaultdict(list)
    markers = Counter()
    for metadata in catalog['pages']:
        page = json.loads((data / 'pages' / (metadata['id'] + '.json')).read_text(encoding='utf-8'))
        soup = BeautifulSoup(page['html'], 'html.parser')
        for pair in soup.select('.vt-pair'):
            english = pair.find(class_='vt-en', recursive=False)
            chinese = pair.find(class_='vt-zh', recursive=False)
            if english is None or chinese is None:
                continue
            totals['bilingualPairs'] += 1
            markers.update(node.get('data-term', '').casefold() for node in chinese.select('.vt-term'))
            candidate = copy.copy(chinese)
            result = annotator.annotate(english, candidate)
            # Auditing is read-only. Also verify suggestions preserve protected content.
            assert [str(node) for node in candidate.select('pre,code,kbd,samp,math')] == [str(node) for node in chinese.select('pre,code,kbd,samp,math')], metadata['id']
            assert [node.get('href') for node in candidate.select('a[href]')] == [node.get('href') for node in chinese.select('a[href]')], metadata['id']
            assert not candidate.select('.vt-term .vt-term'), metadata['id']
            for key in ('source', 'existing', 'added', 'normalized', 'unmatched'):
                totals[key] += result[key]
            for name, counts in result['byTerm'].items():
                terms[name].update(counts)
                if counts['unmatched'] and len(examples[name]) < 3:
                    examples[name].append({'page': metadata['id'], 'english': english.get_text(' ', strip=True)[:280], 'chinese': chinese.get_text(' ', strip=True)[:280]})
    return {
        'pages': len(catalog['pages']), 'configuredTerms': len(annotator.terms),
        'counts': dict(totals), 'existingMarkers': dict(markers.most_common()),
        'terms': {name: {**counts, 'examples': examples[name]} for name, counts in sorted(terms.items(), key=lambda item: (-item[1]['unmatched'], item[0]))},
        'note': 'Unmatched source occurrences are review candidates, not proof of an error: Google may paraphrase, omit, or split a phrase across formatting. No generated page or cache was changed.'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'public/data')
    parser.add_argument('--config', type=Path, default=ROOT / 'terminology.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/terminology-audit-current.json')
    args = parser.parse_args()
    report = audit(args.data, json.loads(args.config.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Audited {report['pages']} pages, {report['counts'].get('bilingualPairs', 0)} bilingual blocks, {report['configuredTerms']} configured terms -> {args.output}")


if __name__ == '__main__':
    main()
