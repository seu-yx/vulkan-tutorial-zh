"""Check content completeness, preserved code, local assets and mirror links."""
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

root = Path(__file__).resolve().parents[1]
catalog = json.loads((root / 'public/data/catalog.json').read_text(encoding='utf-8'))
rendered = json.loads((root / '.local/rendered.json').read_text(encoding='utf-8'))
original = {page['id']: page for page in rendered['pages']}
ids = {page['id'] for page in catalog['pages']}
errors = []
assert ids == set(original), 'Generated catalog does not contain every source page'
navigation = catalog.get('navigation', [])
assert [(entry['title'], entry['depth'], entry.get('id')) for entry in navigation] == [
    (entry['title'], entry['depth'], entry.get('id') if entry.get('id') in ids else None)
    for entry in rendered['navigation']
], 'Generated catalog does not preserve the official navigation hierarchy'
for metadata in catalog['pages']:
    page = json.loads((root / 'public/data/pages' / (metadata['id'] + '.json')).read_text(encoding='utf-8'))
    soup = BeautifulSoup(page['html'], 'html.parser')
    expected = BeautifulSoup(original[page['id']]['html'], 'html.parser')
    if [block.get_text() for block in soup.select('pre')] != [block.get_text() for block in expected.select('pre')]:
        errors.append((page['id'], 'Code listing changed'))
    for node in soup.select('[src], a[href]'):
        address = node.get('src') or node.get('href')
        if address.startswith('/assets/') and not (root / 'public' / unquote(address.lstrip('/'))).is_file():
            errors.append((page['id'], 'Missing asset', address))
        if address.startswith('/?page='):
            linked = parse_qs(urlsplit(address).query).get('page', [''])[0]
            if linked not in ids:
                errors.append((page['id'], 'Missing internal chapter', linked))
    if soup.select('td.vt-en,th.vt-en,dt.vt-en'):
        errors.append((page['id'], 'Translation cell hidden by English wrapper'))
    if soup.select('script,iframe,object,embed,[onclick],[onerror]'):
        errors.append((page['id'], 'Executable upstream content'))
assert not list((root / 'public').rglob('*.pem')), 'Private key in public directory'
for issue in errors[:30]:
    print(*issue, sep=': ')
print(f'Checked {len(ids)} pages; {len(errors)} content issues')
raise SystemExit(bool(errors))
