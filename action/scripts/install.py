"""Turn the entries marked 確認安裝 in state.json into installable Claude bundles inside the library.

CLI: install.py --repo <library checkout> --library-name <owner/repo> --pages <dashboard url> --skill-src <dir> [--push]

Writes, and owns, only these library paths:
  .claude-plugin/marketplace.json  Claude Code plugin marketplace (/plugin marketplace add <owner/repo>)
  plugins/github-box/              this box's own skill as a plugin, so Claude can search and add to the library
  dist/                            skill zips to upload in Claude Chat / Cowork (Settings > Capabilities > Skills)
  INSTALL.md                       what is installed and how to finish the steps that cannot be automated

Third-party repos are cloned without symlinks and only zipped, never executed. Plugins are pinned to the
commit seen at install time, so a later push upstream changes nothing until it is installed again.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import detect

STEM_RE = re.compile(r"^[a-z0-9._-]+__[a-z0-9._-]+$")
FULL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
TRIED = ("未試", "試過", "在用", "放棄")
MARKETPLACE = "github-box"
SELF = "github-box"
ZIP_MAX = 5 * 1024 * 1024
OWNED = (".claude-plugin", "plugins/github-box", "dist", "INSTALL.md")


def load_state(repo: Path) -> dict:
    """state.json is written by the dashboard: {"v": 1, "items": {stem: {"tried", "install", "updated_at"}}}."""
    try:
        data = json.loads((repo / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items() if STEM_RE.match(str(k)) and isinstance(v, dict)}


def load_entries(repo: Path) -> dict:
    try:
        data = json.loads((repo / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    out = {}
    for e in data.get("entries") or [] if isinstance(data, dict) else []:
        m = re.match(r"^library/([^/]+)\.md$", str(e.get("md", ""))) if isinstance(e, dict) else None
        if m and STEM_RE.match(m.group(1)) and isinstance(e.get("repo"), str) and FULL_RE.match(e["repo"]):
            out[m.group(1)] = e
    return out


def plugin_name(full: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", full.split("/", 1)[1].lower()).strip("-") or "plugin"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def clone(full: str, dest: Path, sha: str | None = None) -> str | None:
    """Shallow checkout of `sha` (an earlier pin) or of the default branch head."""
    dest.mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-c", "core.symlinks=false", "-C", str(dest), *a],
                                    capture_output=True, text=True, timeout=300, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    git("init", "-q")
    if git("fetch", "-q", "--depth", "1", f"https://github.com/{full}.git", sha or "HEAD").returncode != 0:
        return None
    if git("checkout", "-q", "FETCH_HEAD").returncode != 0:
        return None
    for link in [p for p in dest.rglob("*") if p.is_symlink()]:
        link.unlink()
    return subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None


def zip_dir(src: Path, out: Path, top: str) -> bool:
    files = [p for p in sorted(src.rglob("*")) if p.is_file() and ".git" not in p.relative_to(src).parts]
    if sum(p.stat().st_size for p in files) > ZIP_MAX:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, f"{top}/{p.relative_to(src).as_posix()}")
    return True


def skill_name(skill_dir: Path, fallback: str) -> str:
    try:
        head = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        head = ""
    m = re.search(r"^name:\s*['\"]?([A-Za-z0-9][A-Za-z0-9_-]{0,63})", head, re.M)
    return m.group(1).lower() if m else fallback


def previous_pins(repo: Path) -> dict:
    """Keep each plugin on the commit it was first installed at; re-mark it to move to the latest."""
    try:
        data = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    out = {}
    for p in data.get("plugins") or [] if isinstance(data, dict) else []:
        src = p.get("source") if isinstance(p, dict) else None
        if isinstance(src, dict) and isinstance(src.get("repo"), str) and SHA_RE.match(str(src.get("sha"))):
            out[src["repo"].lower()] = src["sha"]
    return out


def write_self(repo: Path, src: Path, library: str, pages: str) -> None:
    text = (src / "SKILL.md").read_text(encoding="utf-8").replace("{{LIBRARY}}", library).replace("{{PAGES}}", pages)
    root = repo / "plugins" / SELF
    if root.exists():
        shutil.rmtree(root)
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": SELF, "description": "查詢、收藏與管理我的 GitHub Box 收藏庫", "version": "1.0.0"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "skills" / SELF).mkdir(parents=True)
    (root / "skills" / SELF / "SKILL.md").write_text(text, encoding="utf-8")
    zip_dir(root / "skills" / SELF, repo / "dist" / f"{SELF}.zip", SELF)


def run(repo: Path, library: str, pages: str, skill_src: Path, now: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    state, entries = load_state(repo), load_entries(repo)
    pins = previous_pins(repo)
    for path in ("dist", ".claude-plugin"):
        if (repo / path).exists():
            shutil.rmtree(repo / path)
    write_self(repo, skill_src, library, pages)
    owner = library.split("/", 1)[0]
    plugins = [{"name": SELF, "source": f"./plugins/{SELF}", "description": "查詢、收藏與管理我的 GitHub Box 收藏庫"}]
    taken, rows, marketplaces, problems = {SELF}, [], [], []
    for stem in sorted(state):
        if state[stem].get("install") is not True:
            continue
        e = entries.get(stem)
        inst = detect.check(e.get("installable")) if e else None
        if not e:
            problems.append(f"{stem}：收藏庫裡找不到這筆")
            continue
        if not inst:
            problems.append(f"{e['repo']}：不是 Claude 外掛或 skill，沒有可安裝的東西")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            sha = clone(e["repo"], Path(tmp) / "src", pins.get(e["repo"].lower()))
            if not sha:
                problems.append(f"{e['repo']}：clone 失敗，下次再試")
                continue
            name = plugin_name(e["repo"], taken)
            zips = []
            skill_dirs = inst["skills"] if inst["kind"] == "skill" else [
                p.parent.relative_to(Path(tmp) / "src").as_posix()
                for p in sorted((Path(tmp) / "src").rglob("SKILL.md"))
                if "node_modules" not in p.parts and len(p.parts) < 12][:detect.MAX_SKILLS]
            for d in skill_dirs:
                sd = (Path(tmp) / "src" / d).resolve()
                if not (sd / "SKILL.md").is_file() or not sd.is_relative_to((Path(tmp) / "src").resolve()):
                    continue
                sname = skill_name(sd, name)
                out = repo / "dist" / stem / f"{sname}.zip"
                if zip_dir(sd, out, sname):
                    zips.append(out.relative_to(repo).as_posix())
            if inst["kind"] == "marketplace":
                marketplaces.append(e["repo"])
            else:
                p = {"name": name, "source": {"source": "github", "repo": e["repo"], "sha": sha},
                     "description": str(e.get("tagline") or e["repo"])[:120]}
                if inst["kind"] == "skill":
                    p.update(strict=False, skills=[f"./{d}" if d != "." else "./" for d in inst["skills"]])
                plugins.append(p)
            rows.append({"repo": e["repo"], "kind": inst["kind"], "name": name, "sha": sha[:7], "zips": zips})
    (repo / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (repo / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": MARKETPLACE, "owner": {"name": owner}, "plugins": plugins}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (repo / "INSTALL.md").write_text(render_install(library, pages, rows, marketplaces, problems, now), encoding="utf-8")
    return {"installed": len(rows), "problems": problems}


def render_install(library: str, pages: str, rows: list, marketplaces: list, problems: list, now: str) -> str:
    L = [
        "# 安裝清單", "",
        f"由 GitHub Box 自動產生 · 更新 {now[:10]}。在看板（{pages}）按「確認安裝」後會自動重建這份清單。", "",
        "## Claude Code（只要設定一次）", "",
        "```", f"/plugin marketplace add {library}", f"/plugin install {SELF}@{MARKETPLACE}", "```", "",
        "之後有新的確認安裝時，執行 `/plugin marketplace update " + MARKETPLACE + "`，再 `/plugin install <名稱>@" + MARKETPLACE + "`。", "",
        "## Claude Chat 與 Cowork", "",
        "到 claude.ai › 設定 › Capabilities › Skills 上傳下面的 zip。在看板的條目頁也能直接下載。", "",
        f"- `dist/{SELF}.zip`：GitHub Box 本身（讓 Claude 查你的收藏、幫你收新連結）", "",
        "## 已確認安裝", "",
    ]
    if not rows:
        L.append("（還沒有）")
    for r in rows:
        L.append(f"- **{r['repo']}**（{r['kind']} · `{r['sha']}`）→ Claude Code：`/plugin install {r['name']}@{MARKETPLACE}`")
        L += [f"  - Chat／Cowork：`{z}`" for z in r["zips"]]
    for m in marketplaces:
        L.append(f"- **{m}** 自己就是套件市集 → Claude Code：`/plugin marketplace add {m}`")
    if problems:
        L += ["", "## 沒裝成的", "", *[f"- {p}" for p in problems]]
    return "\n".join(L) + "\n"


def _git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def commit_and_push(repo: Path, counts: dict) -> None:
    _git(repo, "add", "-A", "--", *[p for p in OWNED if (repo / p).exists()])
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    ident = ["-c", "user.name=github-actions[bot]", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com"]
    _git(repo, *ident, "commit", "-q", "-m", f"install: {counts['installed']} 個可安裝項目")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for _ in range(3):
        if _git(repo, "push", "-q", "origin", f"HEAD:{branch}", check=False).returncode == 0:
            return
        _git(repo, *ident, "pull", "-q", "--rebase", "origin", branch, check=False)
    raise RuntimeError("push still rejected after 3 attempts")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--library-name", required=True)
    ap.add_argument("--pages", required=True)
    ap.add_argument("--skill-src", type=Path, required=True)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args(argv)
    if not FULL_RE.match(a.library_name):
        print("bad --library-name", file=sys.stderr)
        return 2
    counts = run(a.repo, a.library_name, a.pages, a.skill_src)
    if a.push:
        commit_and_push(a.repo, counts)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
