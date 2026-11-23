"""Run the reader's JavaScript navigation checks in the shared CI test suite."""
from pathlib import Path
import subprocess
import unittest


class ReaderNavigationTests(unittest.TestCase):
    def test_reader_navigation(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", str(root / "tests/test_navigation.mjs")],
            cwd=root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
