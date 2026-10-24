import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _path import FIXTURES, SCRIPTS  # noqa: F401
import entry
import publish
from helpers import ANALYSIS, meta, write_entry

NOW = "2026-10-18T12:00:00+00:00"
SVG = (FIXTURES / "svg_ok.svg").read_text(encoding="utf-8")
RUN = {"result": {"num_turns": 5, "modelUsage": {"claude-opus-5-5": {}}}, "tools": {"deepwiki": True}}


def capture(url="https://github.com/Owner/Repo", at="2026-10-18T10:00:00+08:00", **kw):
    c = {"v": 1, "url": url, "captured_at": at, "source": "threads"}
    c.update(kw)
    return c


class PublishTest(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.repo = root / "lib"
        self.art = root / "art"
        (self.repo / "inbox").mkdir(parents=True)
        self.art.mkdir()
        self.lib = self.repo / "library"

    def inbox(self, iid, content):
        p = self.repo / "inbox" / f"{iid}.json"
        p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return p

    def leg(self, iid, status="ok", m=None, summary=ANALYSIS, svg=SVG, entry_path=None, error=None,
            capture_obj=None, raw=None, force=False, repo_id="auto", item_id=None, run=RUN):
        d = self.art / f"repobox-out-{iid}"
        d.mkdir()
        item = {"id": item_id or iid, "url": None, "capture": capture_obj, "raw": raw, "force": force}
        (d / "item.json").write_text(json.dumps(item))
        m = meta() if m is None and status != "failed" else m
        if m is not None:
            (d / "meta.json").write_text(json.dumps(m))
        if status == "ok":
            (d / "summary.json").write_text(json.dumps(summary, ensure_ascii=False))
            (d / "run.json").write_text(json.dumps(run))
            if svg:
                (d / "diagram.svg").write_text(svg)
        rid = (m["id"] if m else None) if repo_id == "auto" else repo_id
        st = {"status": status, "error": error, "entry": entry_path, "repo_id": rid, "diagram": bool(svg) and status == "ok",
              "rounds": 1, "wall_s": 200, "claude_exit": 0 if status == "ok" else None}
        (d / "status.json").write_text(json.dumps(st))
        return d

    def run_publish(self):
        return publish.run(self.art, self.repo, now=NOW)

    def md(self, stem="owner__repo"):
        path = self.lib / f"{stem}.md"
        return entry.read_record(path), entry.read_entry(path)[1]

    # --- ok / dedup / failed -------------------------------------------------

    def test_ok_writes_md_svg_and_moves_to_done(self):
        self.inbox("20261018-1", capture())
        self.leg("20261018-1")
        res = self.run_publish()
        self.assertEqual((res["ok"], res["dedup"], res["failed"]), (1, 0, 0))
        fm, user = self.md()
        self.assertEqual(fm["repo_id"], 1)
        self.assertEqual(fm["analysis"], {"model": "claude-opus-5-5", "turns": 5, "wall_s": 200, "rounds": 1,
                                          "deepwiki": True, "diagram": True})
        self.assertEqual([s["id"] for s in fm["sightings"]], ["20261018-1"])
        self.assertEqual(fm["analyzed_at"], NOW)
        self.assertEqual(user, entry.USER_DEFAULT)
        self.assertEqual((self.lib / "owner__repo.svg").read_text(), SVG)
        self.assertIn("![architecture](owner__repo.svg)", (self.lib / "owner__repo.md").read_text())
        self.assertFalse((self.repo / "inbox/20261018-1.json").exists())
        self.assertTrue((self.repo / "inbox/done/20261018-1.json").exists())

    def test_ok_without_svg_has_no_image_and_removes_stale_svg(self):
        write_entry(self.lib, svg=True)
        self.leg("dispatch-1", svg=None, force=True, entry_path="library/owner__repo.md")
        self.run_publish()
        self.assertFalse((self.lib / "owner__repo.svg").exists())
        self.assertNotIn("![architecture]", (self.lib / "owner__repo.md").read_text())
        self.assertFalse(self.md()[0]["analysis"]["diagram"])

    def test_dedup_appends_sighting_keeps_notes_and_auto_block(self):
        old = write_entry(self.lib, sightings=[{"id": "a", "at": "2026-10-01T00:00:00+00:00"}],
                          user="\n## 我的筆記\n- 留著\n", svg=True)
        before_auto = entry.read_auto(old)
        self.inbox("20261018-2", capture(note="again"))
        self.leg("20261018-2", status="dedup", m=meta(stargazers_count=50), entry_path="library/owner__repo.md")
        res = self.run_publish()
        self.assertEqual(res["dedup"], 1)
        fm, user = self.md()
        self.assertEqual([s["id"] for s in fm["sightings"]], ["a", "20261018-2"])
        self.assertEqual(fm["stars"], 50)
        self.assertEqual(user, "\n## 我的筆記\n- 留著\n")
        self.assertEqual(entry.read_auto(old), before_auto)
        self.assertTrue((self.lib / "owner__repo.svg").exists())
        self.assertTrue((self.repo / "inbox/done/20261018-2.json").exists())

    def test_failed_moves_to_failed_with_error(self):
        self.inbox("bad1", "{not json")
        self.leg("bad1", status="failed", error="capture: not valid JSON", raw="{not json")
        cap = {"v": 1, "captured_at": "2026-10-18T10:00:00+08:00"}
        self.inbox("bad2", cap)
        self.leg("bad2", status="failed", error="capture: url is not a GitHub repo URL", capture_obj=cap)
        self.inbox("bad3", capture())
        self.leg("bad3", status="failed", error="resolve: HTTP 404", capture_obj=capture())
        self.inbox("bad4", capture())
        self.leg("bad4", status="ok", summary=dict(ANALYSIS, category="nope"), capture_obj=capture())
        res = self.run_publish()
        self.assertEqual(res["failed"], 4)
        self.assertEqual(sorted(res["failed_ids"]), ["bad1", "bad2", "bad3", "bad4"])
        f1 = json.loads((self.repo / "inbox/failed/bad1.json").read_text())
        self.assertEqual((f1["raw"], f1["capture"], f1["failed_at"]), ("{not json", None, NOW))
        f2 = json.loads((self.repo / "inbox/failed/bad2.json").read_text())
        self.assertEqual(f2["capture"], cap)
        self.assertIn("resolve", json.loads((self.repo / "inbox/failed/bad3.json").read_text())["error"])
        self.assertIn("publish-reject", json.loads((self.repo / "inbox/failed/bad4.json").read_text())["error"])
        self.assertEqual(list((self.repo / "inbox").glob("*.json")), [])
        self.assertFalse(self.lib.exists() and any(self.lib.glob("*.md")))

    def test_dispatch_item_adds_no_sighting_and_moves_nothing(self):
        self.inbox("20261018-9", capture())
        self.leg("dispatch-5", force=True)
        self.run_publish()
        self.assertEqual(self.md()[0]["sightings"], [])
        self.assertTrue((self.repo / "inbox/20261018-9.json").exists())
        self.assertFalse((self.repo / "inbox/done").exists())

    def test_forced_dispatch_on_renamed_repo_updates_old_path(self):
        write_entry(self.lib, "Old/Name", 7, user="\n## 我的筆記\nmine\n", svg=True)
        new = meta("New/Name", 7)
        self.leg("dispatch-6", m=new, force=True, entry_path="library/old__name.md")
        self.run_publish()
        self.assertFalse((self.lib / "new__name.md").exists())
        fm, user = self.md("old__name")
        self.assertEqual(fm["repo"], "New/Name")
        self.assertEqual(user, "\n## 我的筆記\nmine\n")
        self.assertIn("![architecture](old__name.svg)", (self.lib / "old__name.md").read_text())

    # --- grouping and sightings ---------------------------------------------

    def test_two_legs_same_repo_pick_diagram_and_merge_sightings(self):
        self.inbox("20261018-1", capture(at="2026-10-18T10:00:00+08:00"))
        self.inbox("20261018-2", capture(at="2026-10-18T11:00:00+08:00"))
        self.leg("20261018-1", svg=None)
        self.leg("20261018-2")
        res = self.run_publish()
        self.assertEqual(res["ok"], 1)
        fm, _ = self.md()
        self.assertEqual([s["id"] for s in fm["sightings"]], ["20261018-1", "20261018-2"])
        self.assertTrue((self.lib / "owner__repo.svg").exists())
        self.assertTrue(fm["analysis"]["diagram"])
        self.assertEqual(len(list((self.repo / "inbox/done").glob("*.json"))), 2)

    def test_two_captures_same_timestamp_both_kept(self):
        self.inbox("20261018-1", capture())
        self.inbox("20261018-2", capture())
        self.leg("20261018-1")
        self.leg("20261018-2", svg=None)
        self.run_publish()
        self.assertEqual(len(self.md()[0]["sightings"]), 2)

    def test_replay_same_artifacts_is_idempotent(self):
        self.inbox("20261018-1", capture())
        self.leg("20261018-1")
        self.run_publish()
        first = (self.lib / "owner__repo.md").read_text()
        self.run_publish()
        self.assertEqual((self.lib / "owner__repo.md").read_text(), first)

    # --- artifact distrust ---------------------------------------------------

    def test_rejects_entry_path_outside_library(self):
        (self.repo / "README.md").write_text("original")
        self.leg("dispatch-1", status="dedup", entry_path="../README.md")
        res = self.run_publish()
        self.assertEqual(res["failed"], 1)
        self.assertFalse(self.lib.exists() and any(self.lib.glob("*.md")))

    def test_rejects_id_mismatch(self):
        self.inbox("20261018-1", capture())
        self.leg("20261018-1", item_id="20261018-other")
        res = self.run_publish()
        self.assertEqual(res["failed"], 1)
        self.assertIn("publish-reject", json.loads((self.repo / "inbox/failed/20261018-1.json").read_text())["error"])

    def test_rejects_repo_id_mismatch_between_status_and_meta(self):
        self.leg("dispatch-1", repo_id=999)
        self.assertEqual(self.run_publish()["failed"], 1)

    def test_rejects_entry_whose_frontmatter_repo_id_differs(self):
        victim = write_entry(self.lib, "Victim/Repo", 5)
        before = victim.read_text()
        self.leg("dispatch-1", m=meta("Owner/Repo", 1), force=True, entry_path="library/victim__repo.md")
        self.assertEqual(self.run_publish()["failed"], 1)
        self.assertEqual(victim.read_text(), before)

    def test_rejects_meta_wrong_types_without_crashing_batch(self):
        self.leg("dispatch-1", m=meta(stargazers_count="x"))
        self.inbox("20261018-1", capture(url="https://github.com/Good/One"))
        self.leg("20261018-1", m=meta("Good/One", 2))
        res = self.run_publish()
        self.assertEqual((res["ok"], res["failed"]), (1, 1))
        self.assertTrue((self.lib / "good__one.md").exists())

    def test_rejects_hostile_svg_in_artifact(self):
        self.leg("dispatch-1", svg=SVG.replace("</svg>", "<script>x</script></svg>"))
        self.assertEqual(self.run_publish()["failed"], 1)

    def test_missing_status_json_becomes_failed(self):
        d = self.leg("dispatch-1")
        (d / "status.json").unlink()
        self.assertEqual(self.run_publish()["failed"], 1)

    def test_bad_captured_at_becomes_failed(self):
        self.inbox("20261018-1", capture(at="not a date"))
        self.leg("20261018-1")
        res = self.run_publish()
        self.assertEqual(res["failed"], 1)
        self.assertTrue((self.repo / "inbox/failed/20261018-1.json").exists())

    # --- repo-level outputs --------------------------------------------------

    def test_writes_taxonomy_when_missing(self):
        self.run_publish()
        self.assertTrue((self.repo / "taxonomy.yml").exists())

    def test_readme_and_index_regenerated(self):
        self.leg("dispatch-1")
        self.run_publish()
        self.assertIn("Owner/Repo", (self.repo / "README.md").read_text())
        self.assertEqual(json.loads((self.repo / "index.json").read_text())["count"], 1)

    def test_item_without_artifact_becomes_failed(self):
        self.inbox("20261018-1", capture())
        self.inbox("20261018-2", capture(url="https://github.com/Good/One"))
        self.leg("20261018-2", m=meta("Good/One", 2))
        items = [{"id": "20261018-1", "url": "https://github.com/Owner/Repo", "force": False},
                 {"id": "20261018-2", "url": "https://github.com/Good/One", "force": False},
                 {"id": "dispatch-3", "url": "https://github.com/x/y", "force": True},
                 {"id": "../evil", "url": None, "force": False}]
        res = publish.run(self.art, self.repo, now=NOW, items=items)
        self.assertEqual((res["ok"], res["failed"]), (1, 2))
        self.assertNotIn("../evil", res["failed_ids"])
        rec = json.loads((self.repo / "inbox/failed/20261018-1.json").read_text())
        self.assertIn("no artifact", rec["error"])
        self.assertEqual(rec["capture"]["url"], "https://github.com/Owner/Repo")

    def test_malformed_taxonomy_falls_back_and_batch_completes(self):
        (self.repo / "taxonomy.yml").write_text("categories: [unterminated\n", encoding="utf-8")
        self.inbox("20261018-1", capture())
        self.leg("20261018-1")
        res = self.run_publish()
        self.assertEqual(res["ok"], 1)
        self.assertTrue((self.repo / "inbox/done/20261018-1.json").exists())
        self.assertEqual((self.repo / "taxonomy.yml").read_text(), "categories: [unterminated\n")

    def test_publish_writes_sidecar_and_slim_table(self):
        self.inbox("20261018-1", capture())
        self.leg("20261018-1")
        self.run_publish()
        side = json.loads((self.lib / "owner__repo.json").read_text(encoding="utf-8"))
        self.assertEqual(side["sightings"][0]["id"], "20261018-1")
        self.assertEqual(side["analysis"]["turns"], 5)
        head = (self.lib / "owner__repo.md").read_text(encoding="utf-8").split(entry.START, 1)[0]
        self.assertIn("收藏次數: 1", head)
        self.assertNotIn("analysis:", head)

    def test_legacy_entry_migrates_on_dedup(self):
        p = self.lib / "owner__repo.md"
        self.lib.mkdir(parents=True)
        p.write_text("---\nrepo: Owner/Repo\nrepo_id: 1\nstars: 3\ncategory: dev-tool\ntags: [a]\nstack: [Python]\n"
                     "sightings:\n- id: old\n  at: '2026-10-01T00:00:00+08:00'\nanalyzed_at: '2026-10-01T00:00:00+00:00'\n"
                     "analysis:\n  model: m\n---\n" + entry.START + "\n## 技術摘要\n\nx\n" + entry.END + "\n## 我的筆記\n\n",
                     encoding="utf-8")
        self.inbox("20261018-2", capture())
        self.leg("20261018-2", status="dedup", entry_path="library/owner__repo.md")
        self.run_publish()
        rec, user = self.md()
        self.assertEqual([s["id"] for s in rec["sightings"]], ["old", "20261018-2"])
        self.assertEqual(rec["analysis"], {"model": "m"})
        text = p.read_text(encoding="utf-8")
        self.assertNotIn("我的筆記", text)
        self.assertNotIn("analysis:", text.split(entry.START, 1)[0])
        self.assertIn("## 技術摘要", text)

    def test_corrupt_sidecar_fails_leg_without_overwriting(self):
        write_entry(self.lib, sightings=[{"id": "a", "at": "2026-10-01T00:00:00+00:00"}])
        (self.lib / "owner__repo.json").write_text("{broken", encoding="utf-8")
        self.inbox("20261018-2", capture())
        self.leg("20261018-2", status="dedup", entry_path="library/owner__repo.md")
        res = self.run_publish()
        self.assertEqual(res["failed"], 1)
        self.assertEqual((self.lib / "owner__repo.json").read_text(encoding="utf-8"), "{broken")

    def test_dedup_stars_at_uses_batch_time(self):
        write_entry(self.lib)
        self.inbox("20261018-2", capture())
        self.leg("20261018-2", status="dedup", entry_path="library/owner__repo.md")
        publish.run(self.art, self.repo, now="2030-01-02T00:00:00+00:00")
        self.assertEqual(self.md()[0]["stars_at"], "2030-01-02")

    def test_cli_stdout_is_pure_json_despite_index_warnings(self):
        import sys
        self.lib.mkdir(parents=True)
        (self.lib / "junk.md").write_text("---\nrepo: x\n---\n", encoding="utf-8")
        write_entry(self.lib, "Bad/Side", 9)
        (self.lib / "bad__side.json").write_text("{broken", encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPTS / "publish.py"), "--artifacts", str(self.art), "--repo", str(self.repo)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["failed"], 0)
        self.assertIn("skipping", p.stderr)

    def test_publish_sidecar_has_reading_fields(self):
        self.inbox("20261019-1", capture())
        self.leg("20261019-1")
        self.run_publish()
        side = json.loads((self.lib / "owner__repo.json").read_text(encoding="utf-8"))
        self.assertEqual(side["intro"], ANALYSIS["intro"])
        self.assertEqual(side["requirements"], ANALYSIS["requirements"])


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


class PushTest(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.remote = root / "remote.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.a, self.b = root / "a", root / "b"
        git(root, "clone", "-q", str(self.remote), str(self.a))
        for c in (self.a,):
            git(c, "config", "user.email", "t@t"), git(c, "config", "user.name", "t")
        (self.a / "f.txt").write_text("base\n")
        git(self.a, "add", "."), git(self.a, "commit", "-qm", "base"), git(self.a, "push", "-q", "origin", "HEAD:main")
        git(root, "clone", "-q", str(self.remote), str(self.b))
        git(self.b, "config", "user.email", "t@t"), git(self.b, "config", "user.name", "t")

    def test_push_with_retry_rebases(self):
        (self.a / "inbox.json").write_text("{}\n")
        git(self.a, "add", "."), git(self.a, "commit", "-qm", "phone"), git(self.a, "push", "-q", "origin", "HEAD:main")
        (self.b / "library.md").write_text("x\n")
        git(self.b, "add", "."), git(self.b, "commit", "-qm", "publish")
        publish.push_with_retry(self.b, attempts=3)
        log = git(self.remote, "log", "--format=%s", "main").split()
        self.assertEqual(log[:2], ["publish", "phone"])

    def test_push_with_retry_gives_up_on_conflict(self):
        (self.a / "f.txt").write_text("phone\n")
        git(self.a, "commit", "-qam", "phone"), git(self.a, "push", "-q", "origin", "HEAD:main")
        (self.b / "f.txt").write_text("publish\n")
        git(self.b, "commit", "-qam", "publish")
        with self.assertRaises(RuntimeError):
            publish.push_with_retry(self.b, attempts=3)
        self.assertEqual(git(self.b, "status", "--porcelain"), "")
        self.assertFalse((self.b / ".git" / "rebase-merge").exists())

    def test_commit_only_when_changed(self):
        self.assertFalse(publish.commit(self.b, {"ok": 0, "dedup": 0, "failed": 0}))
        (self.b / "README.md").write_text("x\n")
        self.assertTrue(publish.commit(self.b, {"ok": 1, "dedup": 0, "failed": 0}))
        self.assertEqual(git(self.b, "log", "-1", "--format=%s").strip(), "repobox: 1 analyzed, 0 sightings, 0 failed")


if __name__ == "__main__":
    unittest.main()
