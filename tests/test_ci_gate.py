import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ci_gate', Path(__file__).resolve().parents[1] / 'scripts/ci_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GitGateTests(unittest.TestCase):
    now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)

    def test_unchanged_and_complete_skips_build(self):
        self.assertFalse(gate.needs_build({'commit': 'abc', 'pending': 0}, 'abc', 'schedule')[0])

    def test_new_commit_requires_build(self):
        self.assertTrue(gate.needs_build({'commit': 'abc', 'pending': 0}, 'def', 'schedule')[0])

    def test_pending_translation_resumes_without_new_upstream_commit(self):
        self.assertTrue(gate.needs_build({'commit': 'abc', 'pending': 3}, 'abc', 'schedule')[0])

    def test_project_changes_and_manual_override_rebuild(self):
        state = {'commit': 'abc', 'pending': 0}
        self.assertTrue(gate.needs_build(state, 'abc', 'push')[0])
        self.assertTrue(gate.needs_build(state, 'abc', 'workflow_dispatch', True)[0])

    def test_polish_backfill_resumes_without_an_upstream_change(self):
        state = {'commit': 'abc', 'pending': 0}
        polish = {'version': 1, 'pending': 30, 'retry_after': None}
        self.assertTrue(gate.needs_build(state, 'abc', 'schedule', polish=polish, now=self.now)[0])

    def test_missing_or_finished_polish_inventory_does_not_start_a_build(self):
        state = {'commit': 'abc', 'pending': 0}
        for polish in (None, {}, {'version': 1, 'pending': 0}, {'version': 1, 'pending': 0, 'backfill_complete': True}):
            with self.subTest(polish=polish):
                self.assertFalse(gate.needs_build(state, 'abc', 'schedule', polish=polish, now=self.now)[0])

    def test_polish_service_cooldown_skips_until_the_exact_retry_time(self):
        state = {'commit': 'abc', 'pending': 0}
        polish = {'version': 1, 'pending': 30, 'retry_after': '2026-11-24T12:00:01Z'}
        self.assertFalse(gate.needs_build(state, 'abc', 'schedule', polish=polish, now=self.now)[0])
        polish['retry_after'] = '2026-11-24T12:00:00Z'
        self.assertTrue(gate.needs_build(state, 'abc', 'schedule', polish=polish, now=self.now)[0])
        polish['retry_after'] = '2026-11-24T19:59:59+08:00'
        self.assertTrue(gate.needs_build(state, 'abc', 'schedule', polish=polish, now=self.now)[0])

    def test_polish_cooldown_does_not_block_google_or_project_changes(self):
        complete = {'commit': 'abc', 'pending': 0}
        cooldown = {'version': 1, 'pending': 30, 'retry_after': '2026-12-01T00:00:00Z'}
        for previous, sha, event, force in (
            ({'commit': 'abc', 'pending': 3}, 'abc', 'schedule', False),
            (complete, 'def', 'schedule', False),
            (complete, 'abc', 'push', False),
            (complete, 'abc', 'workflow_dispatch', True),
        ):
            with self.subTest(event=event, sha=sha, force=force):
                self.assertTrue(gate.needs_build(previous, sha, event, force, polish=cooldown, now=self.now)[0])

    def test_disabled_polish_does_not_rebuild_for_its_backlog(self):
        state = {'commit': 'abc', 'pending': 0}
        polish = {'version': 1, 'pending': 30, 'retry_after': None}
        self.assertFalse(gate.needs_build(state, 'abc', 'schedule', polish=polish,
                                         polish_enabled=False, now=self.now)[0])

    def test_invalid_polish_state_does_not_trigger_ai_work(self):
        for polish in (
            {'version': 2, 'pending': 30},
            {'version': 1, 'pending': '30'},
            {'version': 1, 'pending': True},
            {'version': 1, 'pending': -1},
            {'version': 1, 'pending': 30, 'retry_after': 'not-a-date'},
            {'version': 1, 'pending': 30, 'retry_after': '2026-11-24T12:00:00'},
            {'version': 1, 'pending': 30, 'retry_after': 1795521600},
        ):
            with self.subTest(polish=polish):
                self.assertFalse(gate.polish_ready(polish, self.now))


if __name__ == '__main__':
    unittest.main()
