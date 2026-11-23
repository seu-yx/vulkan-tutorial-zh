import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('ci_gate', Path(__file__).resolve().parents[1] / 'scripts/ci_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GitGateTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
