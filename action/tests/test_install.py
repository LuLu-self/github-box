import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from _path import SCRIPTS
import install

SKILL_SRC = SCRIPTS.parent.parent / "skill" / "github-box"
SHA = "a" * 40


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "lib"
        self.upstream = Path(self.tmp.name) / "up"
        self.repo.mkdir()
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_clone(self, full, dest, sha=None):
        self.calls.append((full, sha))
        shutil.copytree(self.upstream / full.replace("/", "__"), dest)
        return sha or SHA

    def upstream_file(self, full, rel, text="x"):
        p = self.upstream / full.replace("/", "__") / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def write(self, entries, state):
        (self.repo / "index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
        (self.repo / "state.json").write_text(json.dumps({"v": 1, "items": state}), encoding="utf-8")

    def run_install(self):
        with mock.patch.object(install, "clone", self.fake_clone):
            return install.run(self.repo, "me/github-box-library", "https://me.github.io/github-box/", SKILL_SRC, now="2026-10-24T00:00:00+00:00")

    def market(self):
        return json.loads((self.repo / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))

    def test_self_plugin_always_present_with_names_filled_in(self):
        self.write([], {})
        self.run_install()
        self.assertEqual(self.market()["plugins"][0]["name"], "github-box")
        skill = (self.repo / "plugins/github-box/skills/github-box/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("me/github-box-library", skill)
        self.assertNotIn("{{", skill)
        with zipfile.ZipFile(self.repo / "dist/github-box.zip") as z:
            self.assertIn("github-box/SKILL.md", z.namelist())

    def test_skill_repo_becomes_pinned_plugin_and_zip(self):
        self.upstream_file("o/skills-pack", "skills/pdf/SKILL.md", "---\nname: pdf-tools\n---\n")
        self.write([{"md": "library/o__skills-pack.md", "repo": "o/skills-pack", "tagline": "PDF 工具",
                     "installable": {"kind": "skill", "skills": ["skills/pdf"]}}],
                   {"o__skills-pack": {"install": True, "tried": "試過"}})
        out = self.run_install()
        self.assertEqual(out["installed"], 1)
        p = self.market()["plugins"][1]
        self.assertEqual(p["source"], {"source": "github", "repo": "o/skills-pack", "sha": SHA})
        self.assertEqual(p["skills"], ["./skills/pdf"])
        self.assertFalse(p["strict"])
        with zipfile.ZipFile(self.repo / "dist/o__skills-pack/pdf-tools.zip") as z:
            self.assertEqual(z.namelist(), ["pdf-tools/SKILL.md"])

    def test_existing_pin_is_reused(self):
        self.upstream_file("o/plug", ".claude-plugin/plugin.json", "{}")
        self.write([{"md": "library/o__plug.md", "repo": "o/plug", "installable": {"kind": "plugin", "skills": []}}],
                   {"o__plug": {"install": True}})
        (self.repo / ".claude-plugin").mkdir()
        (self.repo / ".claude-plugin/marketplace.json").write_text(json.dumps(
            {"plugins": [{"name": "plug", "source": {"source": "github", "repo": "o/plug", "sha": "b" * 40}}]}), encoding="utf-8")
        self.run_install()
        self.assertEqual(self.calls, [("o/plug", "b" * 40)])
        self.assertEqual(self.market()["plugins"][1]["source"]["sha"], "b" * 40)

    def test_not_installable_and_unmarked_are_skipped(self):
        self.write([{"md": "library/o__app.md", "repo": "o/app", "installable": None},
                    {"md": "library/o__other.md", "repo": "o/other", "installable": {"kind": "plugin", "skills": []}}],
                   {"o__app": {"install": True}, "o__other": {"install": False}, "../evil": {"install": True}})
        out = self.run_install()
        self.assertEqual(out["installed"], 0)
        self.assertEqual(len(out["problems"]), 1)
        res = json.loads((self.repo / "dist/installs.json").read_text(encoding="utf-8"))["items"]
        self.assertEqual(res["o__app"]["status"], "problem")
        self.assertEqual(self.calls, [])
        self.assertIn("⚠️ 這個 repo 不是 Claude 外掛或 skill", (self.repo / "INSTALL.md").read_text(encoding="utf-8"))

    def test_root_marketplace_plugin_is_relisted_by_github_source(self):
        self.upstream_file("o/dd", ".claude-plugin/marketplace.json", json.dumps({"plugins": [{"name": "diagram-design", "source": "./"}]}))
        self.upstream_file("o/dd", "skills/diagram-design/SKILL.md", "---\nname: diagram-design\n---\n")
        self.write([{"md": "library/o__dd.md", "repo": "o/dd", "installable": {"kind": "marketplace", "skills": []}}],
                   {"o__dd": {"install": True, "updated_at": "2026-10-24T10:00:00+00:00"}})
        self.run_install()
        p = self.market()["plugins"][1]
        self.assertEqual((p["name"], p["source"]["repo"]), ("diagram-design", "o/dd"))
        res = json.loads((self.repo / "dist/installs.json").read_text(encoding="utf-8"))["items"]["o__dd"]
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["code_cmd"], "/plugin install diagram-design@github-box")
        self.assertEqual(res["zips"], ["dist/o__dd/diagram-design.zip"])
        self.assertEqual(res["requested_at"], "2026-10-24T10:00:00+00:00")
        install_md = (self.repo / "INSTALL.md").read_text(encoding="utf-8")
        self.assertEqual(install_md.count("/plugin install diagram-design@github-box"), 1)

    def test_oversized_skill_is_reported_not_silent(self):
        self.upstream_file("o/big", "skills/big/SKILL.md", "---\nname: big\n---\n")
        self.write([{"md": "library/o__big.md", "repo": "o/big", "installable": {"kind": "skill", "skills": ["skills/big"]}}],
                   {"o__big": {"install": True}})
        with mock.patch.object(install, "ZIP_MAX", 1):
            self.run_install()
        res = json.loads((self.repo / "dist/installs.json").read_text(encoding="utf-8"))["items"]["o__big"]
        self.assertEqual(res["status"], "partial")
        self.assertIn("無法打包", res["problems"][0])

    def test_marketplace_repo_is_listed_not_nested(self):
        self.upstream_file("o/market", ".claude-plugin/marketplace.json", "{}")
        self.write([{"md": "library/o__market.md", "repo": "o/market", "installable": {"kind": "marketplace", "skills": []}}],
                   {"o__market": {"install": True}})
        self.run_install()
        self.assertEqual(len(self.market()["plugins"]), 1)
        self.assertIn("/plugin marketplace add o/market", (self.repo / "INSTALL.md").read_text(encoding="utf-8"))

    def test_plugin_names_are_unique(self):
        taken = {"github-box"}
        self.assertEqual(install.plugin_name("a/Tool_X", taken), "tool-x")
        self.assertEqual(install.plugin_name("b/tool.x", taken), "tool-x-2")


if __name__ == "__main__":
    unittest.main()


class VerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, name, entries):
        p = self.root / name
        with zipfile.ZipFile(p, "w") as z:
            for k, v in entries.items():
                z.writestr(k, v)
        return p

    def test_check_zip(self):
        ok = self.make_zip("ok.zip", {"s/SKILL.md": "---\nname: s\ndescription: d\n---\n"})
        self.assertIsNone(install.check_zip(ok))
        self.assertIn("單一", install.check_zip(self.make_zip("two.zip", {"a/SKILL.md": "x", "b/x": "y"})))
        self.assertIn("SKILL.md", install.check_zip(self.make_zip("none.zip", {"a/README.md": "x"})))
        self.assertIn("name", install.check_zip(self.make_zip("bad.zip", {"a/SKILL.md": "---\ntitle: x\n---\n"})))

    def test_verify_retries_then_succeeds(self):
        calls = []

        def fake(cfg, *args):
            calls.append(args)
            ok = args[1] == "marketplace" or len([c for c in calls if c[1] == "install"]) >= 2
            return mock.Mock(returncode=0 if ok else 1, stdout="", stderr="boom")

        rows = [{"name": "p", "zips": [], "problems": []}]
        with mock.patch.object(install, "_claude", fake), mock.patch.object(install.shutil, "which", return_value="/bin/claude"):
            install.verify(self.root, rows)
        self.assertEqual(rows[0]["checks"]["code"], "ok")
        self.assertIn("第 2 次", rows[0]["checks"]["detail"][0])

    def test_verify_reports_failure_after_retries(self):
        fake = lambda cfg, *args: mock.Mock(returncode=0 if args[1] == "marketplace" else 1, stdout="", stderr="no such plugin")
        rows = [{"name": "p", "zips": [], "problems": []}]
        with mock.patch.object(install, "_claude", fake), mock.patch.object(install.shutil, "which", return_value="/bin/claude"):
            install.verify(self.root, rows)
        self.assertEqual(rows[0]["checks"]["code"], "fail")
        self.assertIn("no such plugin", rows[0]["problems"][0])
        self.assertEqual(install._status({**rows[0], "code_cmd": "x", "market_cmd": None}), "partial")
