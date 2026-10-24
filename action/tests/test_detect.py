import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS  # noqa: F401
import detect


class DetectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, rel):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")

    def test_nothing(self):
        self.touch("README.md")
        self.assertIsNone(detect.detect(self.root))

    def test_marketplace_wins(self):
        self.touch(".claude-plugin/marketplace.json")
        self.touch(".claude-plugin/plugin.json")
        self.assertEqual(detect.detect(self.root), {"kind": "marketplace", "skills": []})

    def test_plugin(self):
        self.touch(".claude-plugin/plugin.json")
        self.assertEqual(detect.detect(self.root)["kind"], "plugin")

    def test_skills_found_including_dot_claude_and_root(self):
        self.touch("SKILL.md")
        self.touch(".claude/skills/a/SKILL.md")
        self.touch("skills/b/SKILL.md")
        self.touch("node_modules/x/SKILL.md")
        self.assertEqual(detect.detect(self.root), {"kind": "skill", "skills": [".", ".claude/skills/a", "skills/b"]})

    def test_check_is_fail_closed(self):
        self.assertIsNone(detect.check(None))
        self.assertIsNone(detect.check({"kind": "skill", "skills": []}))
        self.assertIsNone(detect.check({"kind": "evil", "skills": []}))
        self.assertIsNone(detect.check({"kind": "skill", "skills": ["../x"]}))
        self.assertIsNone(detect.check({"kind": "skill", "skills": ["/etc"]}))
        self.assertIsNone(detect.check({"kind": "plugin", "skills": [], "extra": 1}))
        self.assertEqual(detect.check({"kind": "skill", "skills": ["skills/a"]}), {"kind": "skill", "skills": ["skills/a"]})


if __name__ == "__main__":
    unittest.main()
