"""Project annotated HTML into the two text views the reader can display."""

import atexit
import json
from pathlib import Path
import subprocess
from threading import Lock

from bs4 import CData, NavigableString, Tag

PROJECTOR = Path(__file__).with_name('project-term-views.mjs')
CODE_TAGS = {'pre', 'code', 'kbd', 'samp', 'math', 'svg'}
_worker = None
_worker_lock = Lock()


def _close_worker():
    global _worker
    if _worker is not None:
        try:
            _worker.stdin.close()
        except BrokenPipeError:
            pass
        _worker.stdout.close()
        _worker.wait()
        _worker = None


atexit.register(_close_worker)


def _project(batch):
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = subprocess.Popen(
                ['node', str(PROJECTOR)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, encoding='utf-8',
            )
        try:
            _worker.stdin.write(json.dumps(batch, ensure_ascii=False, separators=(',', ':')) + '\n')
            _worker.stdin.flush()
            answer = _worker.stdout.readline()
            if not answer:
                raise RuntimeError('The Node reader text projector exited without returning a batch')
            return json.loads(answer)
        except (OSError, RuntimeError, ValueError, KeyboardInterrupt):
            # Discard the stream so a partial exchange cannot leak into the next batch.
            _close_worker()
            raise


def _term_sibling(node):
    if isinstance(node, Tag) and 'vt-term' in node.get('class', []):
        return node.get_text()
    return ''


def _text_runs(node, trim, english='', in_code=False, in_link=False):
    """Mirror DOM TreeWalker text order and closest(term, code, link) checks."""
    if type(node) in (NavigableString, CData):
        run = {'text': str(node), 'english': english, 'protected': in_code or in_link}
        if trim and not in_code:
            previous, following = _term_sibling(node.previous_sibling), _term_sibling(node.next_sibling)
            if previous:
                run['previousTerm'] = previous
            if following:
                run['nextTerm'] = following
        yield run
    elif isinstance(node, Tag):
        in_code = in_code or node.name in CODE_TAGS
        in_link = in_link or node.name == 'a'
        if in_code:
            english = ''
        elif 'vt-term' in node.get('class', []):
            english = (node.get('data-english') or node.get('data-term') or node.get('title') or '').strip()
        for child in node.children:
            yield from _text_runs(child, trim, english, in_code, in_link)


def project_term_views(blocks, *, trim=True):
    """Return off/on strings and run-level term provenance for each HTML block.

    Body text uses the reader's space trimming. Page and navigation title
    fragments use trim=False, just as when the reader renders these separately.
    The shared JavaScript projector runs once per batch in a reusable process.
    """
    groups = [list(_text_runs(node, trim)) for node in blocks]
    affected = [index for index, runs in enumerate(groups)
                if any(run['english'] or 'previousTerm' in run or 'nextTerm' in run for run in runs)]
    views = {}
    if affected:
        views = dict(zip(affected, _project([groups[index] for index in affected]), strict=True))
    results = []
    for index, runs in enumerate(groups):
        if index in views:
            off, on = views[index]
        else:
            off = on = [run['text'] for run in runs]
        results.append({
            'off': ''.join(off), 'on': ''.join(on),
            'runs': [{'text': before, 'on': after, 'term': run['english'], 'protected': run['protected']}
                     for run, before, after in zip(runs, off, on, strict=True)],
        })
    return results
