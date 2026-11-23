"""Verify the published navigation survives headings and cached page renders."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildNavigationTests(unittest.TestCase):
    def test_navigation_is_reparsed_while_page_html_is_cached(self):
        with tempfile.TemporaryDirectory(prefix="vulkan-navigation-") as temporary:
            upstream = Path(temporary) / "upstream"
            nav = upstream / "antora/modules/ROOT/nav.adoc"
            nav.parent.mkdir(parents=True)
            source = upstream / "en/intro.adoc"
            source.parent.mkdir(parents=True)
            source.write_text("= Introduction\n\nA tutorial page.\n", encoding="utf-8")
            output = Path(temporary) / "rendered.json"

            def render():
                subprocess.run(["node", str(ROOT / "scripts/build.mjs"), "--upstream", str(upstream),
                                "--output", str(output)], check=True, capture_output=True, text=True)
                return json.loads(output.read_text(encoding="utf-8"))

            nav.write_text("* xref:intro.adoc[Introduction]\n", encoding="utf-8")
            first = render()
            nav.write_text("* Engine Architecture\n** xref:intro.adoc[Setup]\n"
                           "*** xref:intro.adoc[Base Code]\n"
                           "* link:https://example.org/source[Repository, window=_blank]\n", encoding="utf-8")
            second = render()
            self.assertEqual([entry["title"] for entry in second["navigation"]],
                             ["Engine Architecture", "Setup", "Base Code", "Repository"])
            self.assertEqual([entry.get("id") for entry in second["navigation"]], [None, "intro", "intro", None])
            self.assertEqual([entry["depth"] for entry in second["navigation"]], [1, 2, 3, 1])
            self.assertEqual(second["navigation"][-1]["href"], "https://example.org/source")
            self.assertEqual(second["pages"][0]["html"], first["pages"][0]["html"])
            self.assertEqual(second["pages"][0]["depth"], 2)
            self.assertEqual(second["pages"][0]["group"], "Engine Architecture")


if __name__ == "__main__":
    unittest.main()
