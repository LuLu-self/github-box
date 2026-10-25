"""Turn the entries marked 確認安裝 in state.json into installable Claude bundles inside the library.

CLI: install.py --repo <library checkout> --library-name <owner/repo> --pages <dashboard url> --skill-src <dir> [--push]

Writes, and owns, only these library paths:
  .claude-plugin/marketplace.json  Claude Code plugin marketplace (/plugin marketplace add <owner/repo>)
  plugins/github-box/              this box's own skill as a plugin, so Claude can search and add to the library
  dist/                            skill zips to upload in Claude Chat / Cowork (Settings > Capabilities > Skills)
  dist/installs.json               per-entry build result the dashboard shows (ready / partial / problem)
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

import yaml

import detect

STEM_RE = re.compile(r"^[a-z0-9._-]+__[a-z0-9._-]+$")
FULL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
TRIED = ("未試", "試過", "在用", "放棄")
MARKETPLACE = "github-box"
SELF = "github-box"
ZIP_MAX = 25 * 1024 * 1024
# claude.ai rejects an uploaded skill zip with more than 200 files; keep a little under it.
UPLOAD_FILE_LIMIT = 200
UPLOAD_FILE_TARGET = 190
# Agent Skills spec / claude.ai docs: name is lowercase letters, digits and hyphens up to 64 chars and must
# equal the top folder; description is required, at most 1,024 chars (one help article says 200).
SKILL_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DESCRIPTION_MAX = 1024
_EXAMPLE_DIRS = {"examples", "example", "samples", "sample", "demo", "demos", "gallery", "screenshots"}
_EXAMPLE_NAME = re.compile(r"^(example|sample|demo)[-_.]", re.I)
_VARIANT = re.compile(r"[-_.](dark|light|full|animated|motion)\.[A-Za-z0-9]+$", re.I)
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


def _is_example(rel: Path) -> bool:
    return bool(_EXAMPLE_NAME.match(rel.name)) or any(part.lower() in _EXAMPLE_DIRS for part in rel.parts[:-1])


PACK_NAME = "packed-files.txt"
PACK_MARK = "===== GITHUB-BOX PACKED FILE: "


def pack_plan(files: list[Path], src: Path, target: int = UPLOAD_FILE_TARGET) -> tuple[list[Path], list[Path]]:
    """Splits files into (kept as real files, merged into PACK_NAME) so the zip fits claude.ai's limit.
    Nothing is dropped. Only text example material is merged: first the dark/full/animated variants,
    then other examples. SKILL.md, references, scripts and templates always stay real files."""
    rel = lambda p: p.relative_to(src)

    def is_text(p: Path) -> bool:
        try:
            p.read_bytes().decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

    # Files SKILL.md itself names must exist as real files (claude.ai: "files that skill.md references must exist").
    skill_md = src / "SKILL.md"
    named = skill_md.read_bytes().decode("utf-8", errors="replace") if skill_md.is_file() else ""
    protected = {p for p in files if rel(p).as_posix() in named}
    direct, packed = list(files), []
    for tier in (lambda p: _is_example(rel(p)) and _VARIANT.search(p.name),
                 lambda p: _is_example(rel(p))):
        if len(direct) + (1 if packed else 0) <= target:
            break
        move = [p for p in direct if tier(p) and p not in protected and is_text(p)]
        direct = [p for p in direct if p not in move]
        packed += move
    return direct, sorted(packed)


def pack_note(name: str, count: int) -> str:
    return (
        "\n> **claude.ai 上傳版說明（GitHub Box 自動加入）**：claude.ai 限制一個 skill 最多 200 個檔案，"
        f"所以這個技能有 {count} 個範例檔沒有刪除，而是原封不動合併在本資料夾的 `{PACK_NAME}` 裡，"
        "每個檔案前面有一行 `" + PACK_MARK + "<原本路徑> =====`。\n"
        "> When an instruction points to a file (for example `assets/example-x-dark.html`) that does not exist in this skill folder, "
        f"it is inside `{PACK_NAME}`. Extract it with Python and read the extracted copy:\n"
        "> `python3 -c \"import sys,pathlib;d=pathlib.Path(sys.argv[1]);t=(d/'" + PACK_NAME + "').read_bytes().decode();"
        "[pathlib.Path('/tmp/" + name + "-files',f).parent.mkdir(parents=True,exist_ok=True) or pathlib.Path('/tmp/" + name + "-files',f).write_bytes(c.encode()) "
        "for f,c in (s.split(' =====\\n',1) for s in t.split('" + PACK_MARK + "')[1:])]\" <this skill folder>`\n"
        f"> then read `/tmp/{name}-files/<原本路徑>`. All other files are complete and unchanged.\n"
    )


def _with_note(skill_md: str, note: str) -> str:
    """Inserts the note right after the YAML frontmatter so name/description stay first."""
    if skill_md.startswith("---"):
        end = skill_md.find("\n---", 3)
        if end != -1:
            cut = skill_md.find("\n", end + 4)
            cut = len(skill_md) if cut == -1 else cut + 1
            return skill_md[:cut] + note + skill_md[cut:]
    return note + skill_md


def unpack(text: str) -> dict[str, str]:
    return {f: c for f, c in (part.split(" =====\n", 1) for part in text.split(PACK_MARK)[1:])}


def zip_dir(src: Path, out: Path, top: str) -> int | None:
    """Writes the zip and returns how many files had to be merged into PACK_NAME to fit claude.ai's
    200-file limit (0 = none), or None when it cannot fit. Every source file ends up in the zip,
    either as itself or byte-for-byte inside PACK_NAME."""
    files = [p for p in sorted(src.rglob("*")) if p.is_file() and ".git" not in p.relative_to(src).parts]
    if sum(p.stat().st_size for p in files) > ZIP_MAX:
        return None
    direct, packed = (files, []) if len(files) <= UPLOAD_FILE_LIMIT else pack_plan(files, src)
    if len(direct) + (1 if packed else 0) > UPLOAD_FILE_LIMIT:
        return None
    entries = {p.relative_to(src).as_posix(): p.read_bytes() for p in direct}
    if packed:
        # Raw bytes, not read_text(): read_text would turn \r\n into \n and silently change CRLF files.
        bundle = "".join(f"{PACK_MARK}{p.relative_to(src).as_posix()} =====\n{p.read_bytes().decode('utf-8')}" for p in packed)
        entries[PACK_NAME] = bundle.encode("utf-8")
        if "SKILL.md" in entries:
            entries["SKILL.md"] = _with_note(entries["SKILL.md"].decode("utf-8", errors="replace"), pack_note(top, len(packed))).encode("utf-8")
        # Completeness: every original file is present, unchanged.
        back = unpack(bundle)
        assert set(back) | (set(entries) - {PACK_NAME}) == {p.relative_to(src).as_posix() for p in files}
        assert all(back[p.relative_to(src).as_posix()].encode("utf-8") == p.read_bytes() for p in packed)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Fixed timestamps keep an unchanged skill byte-identical, so a rebuild adds nothing to git history.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(f"{top}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, entries[name])
    return len(packed)


def skill_name(skill_dir: Path, fallback: str) -> str:
    try:
        head = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        head = ""
    fm = _frontmatter(head) or {}
    name = str(fm.get("name") or "")
    return name if SKILL_NAME_RE.match(name) else fallback


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


def _root_plugins(src: Path) -> list[str]:
    """Plugin names a marketplace repo serves from its own root ("./"), which we can re-list by GitHub source."""
    try:
        data = json.loads((src / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    out = []
    for p in data.get("plugins") or [] if isinstance(data, dict) else []:
        if isinstance(p, dict) and p.get("source") in ("./", ".", "") and isinstance(p.get("name"), str):
            out.append(p["name"])
    return out


def _skill_dirs(src: Path, inst: dict) -> list[str]:
    if inst["kind"] == "skill":
        return inst["skills"]
    return [p.parent.relative_to(src).as_posix() for p in sorted(src.rglob("SKILL.md"))
            if "node_modules" not in p.parts and len(p.relative_to(src).parts) < 12][:detect.MAX_SKILLS]


def _build_one(repo: Path, stem: str, e: dict, inst: dict, pin: str | None, taken: set) -> tuple[dict, dict | None]:
    """Returns (row for INSTALL.md / installs.json, marketplace plugin entry or None)."""
    row = {"repo": e["repo"], "kind": inst["kind"], "name": None, "sha": None, "skills": [], "zips": [], "packed": 0,
           "code_cmd": None, "market_cmd": None, "problems": []}
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        sha = clone(e["repo"], src, pin)
        if not sha:
            row["problems"].append("下載原始碼失敗，下次重新按確認安裝再試")
            return row, None
        row["sha"] = sha
        for d in _skill_dirs(src, inst):
            sd = (src / d).resolve()
            if not (sd / "SKILL.md").is_file() or not sd.is_relative_to(src.resolve()):
                continue
            sname = skill_name(sd, plugin_name(e["repo"], set()))
            row["skills"].append(sname)
            out = repo / "dist" / stem / f"{sname}.zip"
            dropped = zip_dir(sd, out, sname)
            if dropped is None:
                row["problems"].append(f"技能 {sname} 超過 {ZIP_MAX // (1024 * 1024)}MB 或檔案數無法壓到 {UPLOAD_FILE_LIMIT} 個以內，無法打包給 Chat／Cowork 上傳")
                continue
            row["zips"].append(out.relative_to(repo).as_posix())
            row["packed"] += dropped
        plugin = None
        if inst["kind"] == "marketplace":
            served = _root_plugins(src)
            if served:
                own = e["repo"].split("/")[0] + "/" + served[0]
                name = plugin_name(own if re.match(r"^[a-z0-9-]{1,64}$", served[0]) else e["repo"], taken)
                plugin = {"name": name, "source": {"source": "github", "repo": e["repo"], "sha": sha},
                          "description": str(e.get("tagline") or e["repo"])[:120]}
            else:
                row["market_cmd"] = f"/plugin marketplace add {e['repo']}"
        else:
            name = plugin_name(e["repo"], taken)
            plugin = {"name": name, "source": {"source": "github", "repo": e["repo"], "sha": sha},
                      "description": str(e.get("tagline") or e["repo"])[:120]}
            if inst["kind"] == "skill":
                plugin.update(strict=False, skills=[f"./{d}" if d != "." else "./" for d in inst["skills"]])
        if plugin:
            row["name"] = plugin["name"]
            row["code_cmd"] = f"/plugin install {plugin['name']}@{MARKETPLACE}"
        return row, plugin


VERIFY_TRIES = 3


def _frontmatter(text: str) -> dict | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def check_zip(path: Path) -> str | None:
    """None when the zip is uploadable: one top folder holding SKILL.md with name and description."""
    try:
        with zipfile.ZipFile(path) as z:
            if z.testzip() is not None:
                return "zip 檔損壞"
            names = z.namelist()
            if len(names) > UPLOAD_FILE_LIMIT:
                return f"zip 有 {len(names)} 個檔案，超過 claude.ai 上傳上限 {UPLOAD_FILE_LIMIT}"
            packs = [n for n in names if n.endswith("/" + PACK_NAME)]
            tops = {n.split("/")[0] for n in names}
            if len(tops) != 1:
                return "zip 最上層不是單一技能資料夾"
            top = tops.pop()
            head = z.read(f"{top}/SKILL.md").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return "zip 裡找不到最上層的 SKILL.md"
    fm = _frontmatter(head)
    if fm is None or not fm.get("name") or not fm.get("description"):
        return "SKILL.md 開頭缺少 YAML frontmatter 的 name 或 description"
    if not SKILL_NAME_RE.match(str(fm["name"])):
        return f"name「{fm['name']}」只能用小寫英文、數字、連字號，最多 64 字"
    if str(fm["name"]) != top:
        return f"zip 最上層資料夾「{top}」必須和 name「{fm['name']}」相同"
    if len(str(fm["description"])) > DESCRIPTION_MAX:
        return f"description 有 {len(str(fm['description']))} 字，超過 {DESCRIPTION_MAX} 字上限"
    if packs and PACK_NAME not in head:
        return f"有 {PACK_NAME} 但 SKILL.md 沒有說明怎麼取用"
    return None


def _claude(cfg: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg), "GIT_TERMINAL_PROMPT": "0", "DISABLE_AUTOUPDATER": "1"}
    return subprocess.run(["claude", *args], capture_output=True, text=True, timeout=300, env=env)


def verify(repo: Path, rows: list[dict]) -> None:
    """Re-checks every bundle the way the owner will install it, retrying a failed Claude Code install.

    Sets row["checks"] = {"code": ok|fail|skip, "zip": ok|fail|none, "detail": [...]}. Plugins are only
    downloaded into a throwaway config dir, never run.
    """
    have_cli = shutil.which("claude") is not None
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        market_ok = have_cli and _claude(cfg, "plugin", "marketplace", "add", str(repo)).returncode == 0
        for row in rows:
            detail, code = [], "skip"
            if row.get("name"):
                if not market_ok:
                    detail.append("這次沒辦法執行 Claude Code 安裝測試")
                else:
                    for attempt in range(1, VERIFY_TRIES + 1):
                        r = _claude(cfg, "plugin", "install", f"{row['name']}@{MARKETPLACE}")
                        if r.returncode == 0:
                            code = "ok"
                            if attempt > 1:
                                detail.append(f"Claude Code 安裝測試第 {attempt} 次才成功")
                            break
                        code = "fail"
                    if code == "fail":
                        detail.append(f"Claude Code 安裝測試重試 {VERIFY_TRIES} 次都失敗：{(r.stderr or r.stdout).strip()[-200:]}")
            zips = "none"
            for z in row["zips"]:
                err = check_zip(repo / z)
                zips = "fail" if err or zips == "fail" else "ok"
                if err:
                    detail.append(f"{z.split('/')[-1]}：{err}")
            row["checks"] = {"code": code, "zip": zips, "detail": detail}
            row["problems"] += [d for d in detail if "失敗" in d or "zip" in d or "SKILL" in d]


def _status(row: dict) -> str:
    usable = row["code_cmd"] or row["market_cmd"] or row["zips"]
    return "problem" if not usable else ("partial" if row["problems"] else "ready")


def run(repo: Path, library: str, pages: str, skill_src: Path, now: str | None = None, check: bool = False) -> dict:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    state, entries = load_state(repo), load_entries(repo)
    pins = previous_pins(repo)
    for path in ("dist", ".claude-plugin"):
        if (repo / path).exists():
            shutil.rmtree(repo / path)
    write_self(repo, skill_src, library, pages)
    owner = library.split("/", 1)[0]
    plugins = [{"name": SELF, "source": f"./plugins/{SELF}", "description": "查詢、收藏與管理我的 GitHub Box 收藏庫"}]
    taken, rows, results = {SELF}, [], {}
    for stem in sorted(state):
        if state[stem].get("install") is not True:
            continue
        e = entries.get(stem)
        inst = detect.check(e.get("installable")) if e else None
        if not e:
            row = {"repo": stem, "kind": None, "name": None, "sha": None, "skills": [], "zips": [], "code_cmd": None,
                   "market_cmd": None, "problems": ["收藏庫裡找不到這筆"]}
        elif not inst:
            row = {"repo": e["repo"], "kind": None, "name": None, "sha": None, "skills": [], "zips": [], "code_cmd": None,
                   "market_cmd": None, "problems": ["這個 repo 不是 Claude 外掛或 skill，沒有可以裝進 Claude 的東西"]}
        else:
            row, plugin = _build_one(repo, stem, e, inst, pins.get(e["repo"].lower()), taken)
            if plugin:
                plugins.append(plugin)
        rows.append((stem, row))
    (repo / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (repo / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": MARKETPLACE, "owner": {"name": owner}, "plugins": plugins}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if check:
        verify(repo, [r for _, r in rows])
    for stem, row in rows:
        results[stem] = {**row, "sha": (row["sha"] or "")[:7] or None, "status": _status(row),
                         "requested_at": str(state[stem].get("updated_at") or ""), "built_at": now}
    rows = [r for _, r in rows]
    (repo / "dist").mkdir(parents=True, exist_ok=True)
    (repo / "dist" / "installs.json").write_text(json.dumps({"v": 1, "built_at": now, "items": results},
                                                            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (repo / "INSTALL.md").write_text(render_install(library, pages, rows, now), encoding="utf-8")
    return {"installed": sum(1 for r in results.values() if r["status"] != "problem"),
            "problems": [f"{r['repo']}：{p}" for r in rows for p in r["problems"]]}


def render_install(library: str, pages: str, rows: list, now: str) -> str:
    L = [
        "# 安裝清單", "",
        f"由 GitHub Box 自動產生 · 更新 {now[:10]}。在看板（{pages}）按「確認安裝」後會自動重建這份清單。", "",
        "## Claude Code（只要設定一次）", "",
        "```", f"/plugin marketplace add {library}", f"/plugin install {SELF}@{MARKETPLACE}", "```", "",
        "之後有新的確認安裝時，執行 `/plugin marketplace update " + MARKETPLACE + "`，再執行下面各項的安裝指令。", "",
        "## Claude Chat 與 Cowork", "",
        "到 claude.ai › 設定 › Capabilities › Skills 上傳下面的 zip。在看板的條目頁也能直接下載。", "",
        f"- `dist/{SELF}.zip`：GitHub Box 本身（讓 Claude 查你的收藏、幫你收新連結）", "",
        "## 讓 Claude 每次開始任務前先查收藏", "",
        "skill 會自己判斷時機。想更確定的話，把下面這段加到 Claude Code 的 `~/.claude/CLAUDE.md`，"
        "以及 claude.ai › 設定 › 個人偏好（Chat 和 Cowork 都會套用）：", "",
        "```", "開始任何實質任務前，先用 github-box skill 查我的 GitHub 收藏裡有沒有適合這個任務的工具；"
        "有就用一兩行推薦再開始，沒有就直接開始，不用說查過。", "```", "",
        "## 已確認安裝", "",
    ]
    if not rows:
        L.append("（還沒有）")
    for r in rows:
        head = f"- **{r['repo']}**" + (f"（{r['kind']} · `{(r['sha'] or '')[:7]}`）" if r["sha"] else "")
        L.append(head)
        if r["code_cmd"]:
            L.append(f"  - Claude Code：`{r['code_cmd']}`")
        if r["market_cmd"]:
            L.append(f"  - Claude Code：它自己就是套件市集，執行 `{r['market_cmd']}` 後用 `/plugin` 選要裝的")
        L += [f"  - Chat／Cowork：上傳 `{z}`" for z in r["zips"]]
        if r.get("packed"):
            L.append(f"  - ℹ️ claude.ai 限制 {UPLOAD_FILE_LIMIT} 個檔案，所以 {r['packed']} 個範例檔原封不動合併在 zip 內的 `{PACK_NAME}`，內容完整、沒有刪除；Claude Code 版是原始檔案")
        L += [f"  - ⚠️ {p}" for p in r["problems"]]
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
    ap.add_argument("--verify", action="store_true", help="install each plugin in a throwaway Claude Code config and check zips")
    a = ap.parse_args(argv)
    if not FULL_RE.match(a.library_name):
        print("bad --library-name", file=sys.stderr)
        return 2
    counts = run(a.repo, a.library_name, a.pages, a.skill_src, check=a.verify)
    if a.push:
        commit_and_push(a.repo, counts)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
