import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS  # noqa: F401
import taxonomy


class TaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_default_has_eight_names_in_order(self):
        self.assertEqual(taxonomy.names(taxonomy.DEFAULT), [
            "agent-framework", "mcp-server", "dev-tool", "model-inference",
            "data-processing", "frontend", "infrastructure", "other",
        ])
        for c in taxonomy.DEFAULT:
            self.assertTrue(c["definition"])

    def test_load_missing_returns_default(self):
        self.assertEqual(taxonomy.load(None), taxonomy.DEFAULT)
        self.assertEqual(taxonomy.load(self.tmp / "nope.yml"), taxonomy.DEFAULT)

    def test_load_file_overrides(self):
        p = self.tmp / "taxonomy.yml"
        p.write_text("categories:\n  - name: alpha\n    definition: 第一\n  - name: beta\n", encoding="utf-8")
        cats = taxonomy.load(p)
        self.assertEqual(taxonomy.names(cats), ["alpha", "beta"])
        self.assertEqual(cats[1]["definition"], "")

    def test_load_rejects_duplicate_and_bad_name(self):
        p = self.tmp / "taxonomy.yml"
        p.write_text("categories:\n  - name: alpha\n  - name: alpha\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            taxonomy.load(p)
        p.write_text("categories:\n  - name: Bad Name\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            taxonomy.load(p)

    def test_write_default_roundtrip(self):
        p = self.tmp / "taxonomy.yml"
        taxonomy.write_default(p)
        self.assertEqual(taxonomy.load(p), taxonomy.DEFAULT)

    def test_render_for_prompt(self):
        text = taxonomy.render_for_prompt(taxonomy.DEFAULT)
        self.assertIn("- mcp-server: ", text)
        self.assertEqual(len(text.splitlines()), 8)

    def test_load_syntax_error_raises_value_error(self):
        p = self.tmp / "taxonomy.yml"
        p.write_text("categories: [unterminated\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            taxonomy.load(p)
        p.write_bytes(b"\xff\xfe bad")
        with self.assertRaises(ValueError):
            taxonomy.load(p)

    def test_load_or_default_falls_back(self):
        p = self.tmp / "taxonomy.yml"
        p.write_text("categories: [unterminated\n", encoding="utf-8")
        self.assertEqual(taxonomy.load_or_default(p), taxonomy.DEFAULT)
        p.write_text("categories:\n  - name: alpha\n", encoding="utf-8")
        self.assertEqual(taxonomy.names(taxonomy.load_or_default(p)), ["alpha"])


if __name__ == "__main__":
    unittest.main()
