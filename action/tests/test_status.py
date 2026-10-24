import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _path import SCRIPTS

KEYS = ["status", "error", "entry", "repo_id", "diagram", "rounds", "wall_s", "claude_exit"]


def write(*args):
    out = Path(tempfile.mkdtemp()) / "status.json"
    p = subprocess.run([sys.executable, str(SCRIPTS / "status.py"), str(out), *args], capture_output=True, text=True)
    return p.returncode, (json.loads(out.read_text()) if out.exists() else None), p.stderr


class StatusTest(unittest.TestCase):
    def test_dedup_defaults_complete(self):
        code, s, _ = write("--status", "dedup", "--entry", "library/a__b.md", "--repo-id", "5")
        self.assertEqual(code, 0)
        self.assertEqual(list(s), KEYS)
        self.assertEqual(s, {"status": "dedup", "error": None, "entry": "library/a__b.md", "repo_id": 5,
                             "diagram": False, "rounds": 0, "wall_s": 0, "claude_exit": None})

    def test_failed_defaults_complete(self):
        _, s, _ = write("--status", "failed", "--error", "resolve: 404")
        self.assertEqual(list(s), KEYS)
        self.assertEqual(s["error"], "resolve: 404")

    def test_ok_full(self):
        _, s, _ = write("--status", "ok", "--repo-id", "1", "--diagram", "--rounds", "2", "--wall-s", "300",
                        "--claude-exit", "0")
        self.assertEqual((s["diagram"], s["rounds"], s["wall_s"], s["claude_exit"], s["entry"]), (True, 2, 300, 0, None))

    def test_empty_strings_mean_null(self):
        _, s, _ = write("--status", "ok", "--entry", "", "--repo-id", "", "--claude-exit", "")
        self.assertEqual((s["entry"], s["repo_id"], s["claude_exit"]), (None, None, None))

    def test_bad_status_rejected(self):
        code, s, _ = write("--status", "weird")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
