"""Library entries (library/<slug>.md): rendering, parsing, lookup by repo_id, sightings.

The pipeline owns the frontmatter and the text between START and END. Anything a user writes
after the first END is preserved byte for byte; no notes heading is generated any more.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

import profile

START = "<!-- repobox:auto:start -->"
END = "<!-- repobox:auto:end -->"
USER_DEFAULT = "\n"
# Entries rendered before 2026-10-18 carried an empty notes heading; it is dropped on rewrite.
LEGACY_EMPTY_NOTES = "## 我的筆記"
NOTE_MAX = 500
_TAG = re.compile(r"<[^>]*>", re.S)
_MD_SPECIAL = re.compile(r"([\\`*_\[\]()#!|~])")
# GFM autolinks bare URLs and emails even without link syntax; these go into code spans.
_AUTOLINK = re.compile(r"(?:https?://|www\.)\S+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
# Full record: written to the hidden sidecar library/<stem>.json.
READING_KEYS = ("tagline", "intro", "examples", "requirements", "summary", "highlights", "purpose", "scenarios",
                "verdict", "verdict_reason", "capabilities", "fit", "risks", "unverified", "tasks")
FM_KEYS = ("repo", "repo_id", "url", "description", "language", "stars", "stars_at", "license", "category",
           "tags", "stack", "task_areas", *READING_KEYS, "sources", "installable", "activity", "sightings", "analyzed_at", "analysis")
# Visible table: GitHub renders every frontmatter key, so only human-facing fields go here.
DISPLAY_KEYS = ("repo", "repo_id", "url", "description", "language", "stars", "license", "category", "tags", "stack")
SEEN_COUNT, LAST_SEEN = "收藏次數", "最後看到"
CARRIED_ON_DEDUP = ("category", "tags", "stack", "task_areas", "analyzed_at", "analysis", *READING_KEYS, "sources", "installable")
PAGE_RE = re.compile(r"^https://[^\s<>\"']{1,300}$")


def slug(full_name: str) -> str:
    return full_name.lower().replace("/", "__")


def to_plain(s: str) -> str:
    s = str(s)
    for _ in range(5):
        decoded = html.unescape(s)
        if decoded == s:
            break
        s = decoded
    while True:
        stripped = _TAG.sub("", s)
        if stripped == s:
            break
        s = stripped
    # After this no "<!--" can exist, so model text can never forge a marker.
    s = s.replace("<", "＜").replace(">", "＞")
    return " ".join(s.split())


def md_escape(s: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", s)


def safe_text(s) -> str:
    plain, out, pos = to_plain(s), [], 0
    for m in _AUTOLINK.finditer(plain):
        out.append(md_escape(plain[pos:m.start()]))
        out.append("`" + m.group(0).replace("`", "") + "`")
        pos = m.end()
    out.append(md_escape(plain[pos:]))
    return "".join(out)


def _split(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end + 1])
            except yaml.YAMLError:
                fm = None
            return (fm if isinstance(fm, dict) else {}), text[end + 5:]
    return {}, text


def read_entry(path: Path) -> tuple[dict, str]:
    fm, body = _split(Path(path).read_text(encoding="utf-8"))
    if END in body:
        return fm, body.split(END, 1)[1]
    return fm, body


def read_auto(path: Path) -> str | None:
    _, body = _split(Path(path).read_text(encoding="utf-8"))
    if START not in body:
        return None
    after = body.split(START, 1)[1]
    return after.split(END, 1)[0] if END in after else None


def sidecar(md_path: Path) -> Path:
    return Path(md_path).with_suffix(".json")


def read_record(md_path: Path) -> dict:
    """Frontmatter merged with the sidecar; legacy entries kept everything in frontmatter."""
    fm, _ = read_entry(md_path)
    record = dict(fm)
    side = sidecar(md_path)
    if not side.exists():
        return record
    # A damaged sidecar must stop the write: falling back would overwrite it with a record
    # that has lost its sightings and analysis.
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{side.name}: unreadable sidecar ({e.__class__.__name__})") from e
    if not isinstance(data, dict):
        raise ValueError(f"{side.name}: sidecar is not an object")
    record.update(data)
    return record


def write_entry_files(md_path: Path, record: dict, md_text: str) -> None:
    # Sidecar first: legacy entries keep their machine fields in the .md until this succeeds.
    # default=str turns YAML-parsed dates into strings.
    data = json.dumps({k: record.get(k) for k in FM_KEYS}, ensure_ascii=False, indent=2, default=str)
    side = sidecar(md_path)
    previous = side.read_bytes() if side.is_file() else None
    side.write_text(data + "\n", encoding="utf-8")
    try:
        Path(md_path).write_text(md_text, encoding="utf-8")
    except OSError:
        if previous is None:
            side.unlink(missing_ok=True)
        else:
            side.write_bytes(previous)
        raise


def display_frontmatter(record: dict) -> dict:
    disp = {k: record.get(k) for k in DISPLAY_KEYS}
    if record.get("stars") is not None and record.get("stars_at"):
        disp["stars"] = f"{record['stars']}（{record['stars_at']}）"
    sightings = [s for s in record.get("sightings") or [] if isinstance(s, dict)]
    disp[SEEN_COUNT] = len(sightings)
    if sightings:
        disp[LAST_SEEN] = str(max(sightings, key=_instant).get("at", ""))[:10]
    else:
        disp[LAST_SEEN] = str(record.get("analyzed_at") or "")[:10] or None
    return disp


def find_entry(library: Path, repo_id: int, full_name: str) -> Path | None:
    for p in sorted(Path(library).glob("*.md")):
        try:
            fm, _ = _split(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if fm.get("repo_id") == repo_id:
            return p
    candidate = Path(library) / f"{slug(full_name)}.md"
    return candidate if candidate.exists() else None


def build_frontmatter(meta: dict, analysis: dict | None, sightings: list[dict], prev: dict | None,
                      run: dict | None, now: str | None = None, installable: dict | None = None) -> dict:
    lic = meta.get("license")
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    fm = {
        "repo": meta["full_name"],
        "repo_id": meta["id"],
        "url": meta["html_url"],
        "description": to_plain(meta.get("description") or ""),
        "language": meta.get("language"),
        "stars": meta.get("stargazers_count"),
        "stars_at": now[:10],
        "license": lic.get("spdx_id") if isinstance(lic, dict) else None,
        # Re-read on every sighting, so a repo that went stale or got archived since is shown as such.
        "activity": profile.activity(meta, datetime.fromisoformat(now)),
    }
    if analysis is None:
        prev = prev or {}
        carried = {k: prev.get(k) for k in CARRIED_ON_DEDUP}
    else:
        carried = {
            "category": analysis["category"],
            "tags": list(analysis["tags"]),
            "stack": list(analysis["stack"]),
            "task_areas": list(analysis["task_areas"]),
            "analyzed_at": now,
            "analysis": dict(run) if run is not None else None,
            "sources": list(analysis["sources"]),
            "installable": dict(installable) if installable is not None else None,
        }
        for k in READING_KEYS:
            v = analysis[k]
            carried[k] = [to_plain(x) for x in v] if isinstance(v, list) else to_plain(v)
    fm.update(carried)
    fm["sightings"] = list(sightings)
    return {k: fm[k] for k in FM_KEYS}


def _source_links(full: str, sources: list[str]) -> str:
    return "".join(f"- [{md_escape(p)}](https://github.com/{full}/blob/HEAD/{p})\n" for p in sources)


def _auto_block(analysis: dict, svg_name: str | None, full: str) -> str:
    parts = [
        "\n> " + safe_text(analysis["tagline"]) + "\n",
        "\n## 能不能用：" + safe_text(analysis["verdict"]) + "\n\n" + safe_text(analysis["verdict_reason"]) + "\n",
        "\n## 用途\n\n" + safe_text(analysis["purpose"]) + "\n",
        "\n## 適用情境\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["scenarios"]),
        "\n## 這是什麼\n\n" + safe_text(analysis["intro"]) + "\n\n"
        + "".join(f"- **例如**：{safe_text(e)}\n" for e in analysis["examples"]),
        "\n## 使用門檻\n\n" + "".join(f"- {safe_text(r)}\n" for r in analysis["requirements"]),
        "\n## 實際能力邊界\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["capabilities"]),
        "\n## 對你的應用場景（推論）\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["fit"]),
        "\n## 不適合的情況／風險（推論）\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["risks"]),
        ("\n## 待查證\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["unverified"])) if analysis["unverified"] else "",
        "\n## 可用在哪些任務\n\n" + "".join(f"- {safe_text(x)}\n" for x in analysis["tasks"])
        + "\n任務類型：" + "、".join(safe_text(x) for x in analysis["task_areas"]) + "\n",
        "\n## 技術摘要\n\n" + safe_text(analysis["summary"]) + "\n",
        "\n## 值得借鏡\n\n" + "".join(f"- {safe_text(h)}\n" for h in analysis["highlights"]),
        "\n## 技術棧\n\n" + " · ".join(safe_text(s) for s in analysis["stack"]) + "\n",
    ]
    if svg_name:
        parts.append(f"\n## 架構圖\n\n![architecture]({svg_name})\n")
    parts.append(f"\n## 原始出處\n\n- [{md_escape(full)}](https://github.com/{full})\n" + _source_links(full, analysis["sources"]))
    return "".join(parts)


def render_entry(fm: dict, analysis: dict | None, svg_name: str | None, user_section: str | None,
                 auto: str | None = None) -> str:
    if analysis is not None:
        block = _auto_block(analysis, svg_name, fm["repo"])
    elif auto is not None:
        block = auto
    else:
        raise ValueError("render_entry needs either analysis or the previous auto block")
    if user_section is not None and user_section.strip() == LEGACY_EMPTY_NOTES:
        user_section = None
    head = "---\n" + yaml.safe_dump(display_frontmatter(fm), allow_unicode=True, sort_keys=False, width=1000) + "---\n"
    text = head + START + block + END + (user_section if user_section is not None else USER_DEFAULT)
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError("rendered entry must contain exactly one ordered auto marker pair")
    return text


def write_sighting(item_id: str, capture: dict) -> dict:
    return {
        "id": item_id,
        "at": capture["captured_at"],
        "source": to_plain(capture.get("source") or ""),
        "note": to_plain(capture.get("note") or "")[:NOTE_MAX],
        "page": page if isinstance(page := capture.get("page_url"), str) and PAGE_RE.match(page) else "",
    }


def merge_sightings(prev: list[dict], new: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in [*prev, *new]:
        sid = s.get("id") if isinstance(s, dict) else None
        if sid is not None:
            if sid in seen:
                continue
            seen.add(sid)
        out.append(s)
    return sorted(out, key=_instant)


def _instant(s) -> datetime:
    try:
        t = datetime.fromisoformat(str(s.get("at")))
    except (AttributeError, TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
