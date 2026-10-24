import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS
import prompt


def run(*args):
    p = subprocess.run([sys.executable, str(SCRIPTS / "prompt.py"), *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


class PromptTest(unittest.TestCase):
    def test_analyze_contains_all_values(self):
        code, out, _ = run("analyze", "--full", "Owner/Repo", "--target", "/t", "--out", "/o",
                           "--skill", "/s/SKILL.md", "--taxonomy", "-")
        self.assertEqual(code, 0)
        for v in ("Owner/Repo", "/t", "/o/summary.json", "/o/diagram.svg", "/s/SKILL.md", "no shell"):
            self.assertIn(v, out)
        self.assertNotIn("$", out)

    def test_analyze_lists_taxonomy_lines(self):
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", "-")
        self.assertIn("- mcp-server: ", out)
        tmp = Path(tempfile.mkdtemp()) / "taxonomy.yml"
        tmp.write_text("categories:\n  - name: only-one\n    definition: 唯一\n", encoding="utf-8")
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", str(tmp))
        self.assertIn("- only-one: 唯一", out)
        self.assertNotIn("mcp-server", out)

    def test_fix_contains_check_text(self):
        check = Path(tempfile.mkdtemp()) / "check.txt"
        check.write_text("✗ diagram.svg (1 錯誤)\n    E: node overlaps\n", encoding="utf-8")
        code, out, _ = run("fix", "--out", "/o", "--check", str(check))
        self.assertEqual(code, 0)
        self.assertIn("E: node overlaps", out)
        self.assertIn("/o/diagram.svg", out)

    def test_missing_variable_raises(self):
        with self.assertRaises(KeyError):
            string.Template(prompt.ANALYZE.read_text(encoding="utf-8")).substitute(FULL="x")

    def test_dollar_in_check_text_is_literal(self):
        check = Path(tempfile.mkdtemp()) / "check.txt"
        check.write_text("value $OUT and ${TARGET} stay\n", encoding="utf-8")
        _, out, _ = run("fix", "--out", "/o", "--check", str(check))
        self.assertIn("value $OUT and ${TARGET} stay", out)

    def test_fix_summary_contains_errors_and_limits(self):
        errs = Path(tempfile.mkdtemp()) / "errs.txt"
        errs.write_text("highlights: 2-3 Chinese sentences of 10-120 chars\n", encoding="utf-8")
        code, out, _ = run("fix-summary", "--out", "/o", "--errors", str(errs))
        self.assertEqual(code, 0)
        self.assertIn("highlights: 2-3 Chinese sentences of 10-120 chars", out)
        self.assertIn("/o/summary.json", out)
        self.assertIn("/o/diagram.svg", out)

    def test_analyze_states_length_limits(self):
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", "-")
        for limit in ("600", "120", "30"):
            self.assertIn(limit, out)

    def test_analyze_survives_malformed_taxonomy(self):
        tmp = Path(tempfile.mkdtemp()) / "taxonomy.yml"
        tmp.write_text("categories: [unterminated\n", encoding="utf-8")
        code, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", str(tmp))
        self.assertEqual(code, 0)
        self.assertIn("- mcp-server: ", out)

    def test_analyze_asks_for_plain_intro_and_examples(self):
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", "-")
        self.assertIn('"intro"', out)
        self.assertIn('"examples"', out)
        self.assertIn("jargon", out)

    def test_analyze_asks_for_requirements(self):
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", "-")
        self.assertIn('"requirements"', out)
        self.assertIn("不需安裝", out)

    def test_analyze_asks_for_tagline(self):
        _, out, _ = run("analyze", "--full", "a/b", "--target", "/t", "--out", "/o", "--skill", "/s", "--taxonomy", "-")
        self.assertIn('"tagline"', out)
        self.assertIn("4-20", out)


if __name__ == "__main__":
    unittest.main()
