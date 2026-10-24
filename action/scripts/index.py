"""Library index: README.md (human) and index.json (machine) generated from library/*.md."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import entry
import profile

FULL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
STEM_RE = re.compile(r"^[a-z0-9._-]+__[a-z0-9._-]+$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,39}$")
DESC_MAX = 160
RECENT_N = 10
UNCATEGORIZED = "未分類"
INDEX_FIELDS = ("repo", "repo_id", "url", "description", "tagline", "intro", "requirements", "language", "stars", "license", "category",
                "tags", "stack", "analyzed_at", "purpose", "scenarios", "installable", "verdict", "verdict_reason",
                "tasks", "task_areas", "activity")
RELATED_N = 3
RELATED_MIN = 2.0


def _instant(at) -> datetime:
    return entry._instant({"at": at})


def collect(library: Path) -> list[dict]:
    out = []
    for p in sorted(Path(library).glob("*.md")):
        try:
            fm = entry.read_record(p)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            print(f"index: skipping {p.name}: {e}", file=sys.stderr)
            continue
        repo, rid = fm.get("repo"), fm.get("repo_id")
        if not (isinstance(repo, str) and FULL_RE.match(repo) and isinstance(rid, int) and STEM_RE.match(p.stem)):
            print(f"index: skipping {p.name}: frontmatter missing a valid repo/repo_id", file=sys.stderr)
            continue
        sightings = [s for s in fm.get("sightings") or [] if isinstance(s, dict)]
        times = [s.get("at") for s in sightings if s.get("at")]
        last_seen = max(times, key=_instant) if times else fm.get("analyzed_at")
        e = {k: fm.get(k) for k in INDEX_FIELDS}
        e.update({"md": f"library/{p.name}", "last_seen": str(last_seen or ""), "sightings_n": len(sightings)})
        if (p.parent / f"{p.stem}.svg").exists():
            e["svg"] = f"library/{p.stem}.svg"
        out.append(e)
    return out


def _words(v) -> set[str]:
    return {x.lower() for x in v if isinstance(x, str)} if isinstance(v, list) else set()


def score(a: dict, b: dict) -> float:
    """How related two entries are: same category, overlapping tags (Jaccard), shared stack."""
    s = 2.0 if a.get("category") and a.get("category") == b.get("category") else 0.0
    ta, tb = _words(a.get("tags")), _words(b.get("tags"))
    if ta and tb:
        s += 3.0 * len(ta & tb) / len(ta | tb)
    s += min(2, len(_words(a.get("stack")) & _words(b.get("stack")))) * 0.5
    s += min(2, len(_words(a.get("task_areas")) & _words(b.get("task_areas")))) * 0.75
    return s


def relate(entries: list[dict]) -> list[dict]:
    """Adds `related`: up to RELATED_N other entries' md paths, strongest first. Deterministic, no model."""
    for e in entries:
        ranked = sorted(((score(e, o), o["md"]) for o in entries if o is not e), key=lambda x: (-x[0], x[1]))
        e["related"] = [md for sc, md in ranked if sc >= RELATED_MIN][:RELATED_N]
    return entries


def _newest_first(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: _instant(e["last_seen"]), reverse=True)


def _line(e: dict) -> str:
    desc = entry.to_plain(e.get("description") or "")
    if len(desc) > DESC_MAX:
        desc = desc[:DESC_MAX] + "…"
    stars = e["stars"] if isinstance(e.get("stars"), int) and not isinstance(e.get("stars"), bool) else 0
    parts = [f"- [{e['repo']}]({e['md']})", f"⭐ {stars}"]
    if e.get("verdict") in ("能用", "有條件才能用", "不建議用"):
        parts.append(f"· {e['verdict']}")
    act = e.get("activity") if isinstance(e.get("activity"), dict) else {}
    if act.get("archived") is True:
        parts.append("· 已封存")
    elif act.get("stale") is True:
        parts.append("· 半年未更新")
    if e.get("language"):
        parts.append(f"· {entry.safe_text(e['language'])}")
    text = " ".join(parts)
    if desc:
        text += f" — {entry.safe_text(desc)}"
    raw_tags = e.get("tags") if isinstance(e.get("tags"), list) else []
    tags = [t for t in raw_tags if isinstance(t, str) and TAG_RE.match(t)]
    if tags:
        text += " " + " ".join(f"`{t}`" for t in tags)
    return text


def render_readme(entries: list[dict], cats: list[dict], today: str | None = None) -> str:
    today = today or datetime.now(timezone.utc).date().isoformat()
    ordered = _newest_first(entries)
    lines = ["# RepoBox 收藏庫", "", f"{len(entries)} 個 repo · 更新 {today}", "", "## 最近收藏", ""]
    lines += [_line(e) for e in ordered[:RECENT_N]] or ["（還沒有收藏）"]
    lines += ["", "## 依任務找", ""]
    areas = [a for a in profile.area_names() if any(a in (e.get("task_areas") or []) for e in ordered)]
    for a in areas:
        members = [e for e in ordered if a in (e.get("task_areas") or [])]
        lines += [f"### {a}", "", *(_line(e) for e in members), ""]
    if not areas:
        lines += ["（還沒有）", ""]
    lines += ["## 分類", ""]
    known = {c["name"] for c in cats}
    groups = [(c["name"], c["definition"]) for c in cats] + [(UNCATEGORIZED, "")]
    for name, definition in groups:
        if name == UNCATEGORIZED:
            members = [e for e in ordered if e.get("category") not in known]
        else:
            members = [e for e in ordered if e.get("category") == name]
        if not members:
            continue
        heading = f"### {name}" + (f" — {entry.safe_text(definition)}" if definition else "")
        lines += [heading, "", *(_line(e) for e in members), ""]
    return "\n".join(lines).rstrip() + "\n"


def render_index(entries: list[dict]) -> str:
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": _newest_first(relate([dict(e) for e in entries])),
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
