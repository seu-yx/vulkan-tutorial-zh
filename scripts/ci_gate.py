#!/usr/bin/env python3
"""Decide whether upstream commits, Google translations, or polish need work."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://github.com/KhronosGroup/Vulkan-Tutorial.git'


def polish_ready(state, now=None):
    """Resume a chapter backlog only when its service cooldown has expired."""
    if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 2:
        return False
    pending = state.get('pending', 0)
    if type(pending) is not int or pending <= 0:
        return False
    retry_after = state.get('retry_after')
    if retry_after is None:
        return True
    if not isinstance(retry_after, str):
        return False
    try:
        retry_at = datetime.fromisoformat(retry_after.replace('Z', '+00:00'))
    except ValueError:
        return False
    if retry_at.tzinfo is None:
        return False
    return retry_at <= (now or datetime.now(timezone.utc))


def needs_build(previous, remote_sha, event, force=False, *, polish=None,
                polish_enabled=True, now=None):
    if event == 'push' or force:
        return True, 'project files changed or a rebuild was requested'
    if previous.get('commit') != remote_sha:
        return True, 'upstream Git commit changed'
    if int(previous.get('pending', 0)) > 0:
        return True, 'cached translations have pending paragraphs'
    if polish_enabled and polish_ready(polish, now):
        return True, 'cached polish inventory has pending chapters ready to resume'
    return False, 'upstream Git commit unchanged; no translations or polish ready to resume'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def write_outputs(**outputs):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as destination:
            for key, value in outputs.items():
                destination.write(f'{key}={value}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--record', action='store_true', help='Record the successfully built upstream commit')
    mode.add_argument('--force', action='store_true')
    args = parser.parse_args()
    state_file = ROOT / 'translations/upstream.json'
    if args.record:
        catalog = json.loads((ROOT / 'public/data/catalog.json').read_text(encoding='utf-8'))
        state = {'commit': catalog['upstream']['commit'], 'pending': catalog['translation']['pending'],
                 'provider': 'google', 'source': UPSTREAM, 'branch': 'main'}
        state_file.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        if not state_file.exists() or state_file.read_text(encoding='utf-8') != content:
            state_file.write_text(content, encoding='utf-8')
        print(f"Recorded upstream {state['commit'][:12]}; {state['pending']} pending paragraphs")
        return
    try:
        polish = read_json(ROOT / 'translations/polish-state.json')
    except (OSError, ValueError):
        print('Polish state could not be read; waiting for the next source build to refresh it')
        polish = None
    previous = read_json(state_file) or {}
    enabled = os.environ.get('POLISH_ENABLED', 'true').lower() != 'false'
    result = subprocess.run(['git', 'ls-remote', '--exit-code', UPSTREAM, 'refs/heads/main'],
                            check=True, capture_output=True, text=True, timeout=90)
    remote_sha = result.stdout.split()[0]
    if not re.fullmatch(r'[0-9a-f]{40}', remote_sha):
        raise ValueError('Git returned an invalid upstream commit SHA')
    run, reason = needs_build(
        previous, remote_sha, os.environ.get('GITHUB_EVENT_NAME', 'workflow_dispatch'), args.force,
        polish=polish, polish_enabled=enabled)
    write_outputs(run='true' if run else 'false', upstream_sha=remote_sha)
    print(f"{reason}; upstream {remote_sha[:12]}")


if __name__ == '__main__':
    main()
