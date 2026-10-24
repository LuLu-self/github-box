"""Write analyze artifacts into the library checkout, then optionally commit and push.

CLI: publish.py --artifacts <dir> --repo <library checkout> [--push]

The analyze job ran on untrusted input, so every artifact is re-validated here (load_leg) and a
bad leg is downgraded to failed instead of aborting the batch. Captures are read from the
repo's own inbox files, never from the artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import detect
import entry
import index
import taxonomy
import validate

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
FULL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
ENTRY_RE = re.compile(r"^library/[a-z0-9._-]+__[a-z0-9._-]+\.md$")
PREFIX = "repobox-out-"
RANK = {("ok", True): 0, ("ok", False): 1, ("dedup", False): 2}


class Reject(Exception):
    pass


@dataclass
class Leg:
    id: str | None
    status: str
    error: str | None = None
    entry: str | None = None
    diagram: bool = False
    rounds: int = 0
    wall_s: int = 0
    meta: dict | None = None
    summary: dict | None = None
    svg: str | None = None
    run: dict = field(default_factory=dict)
    from_inbox: bool = False
    capture: dict | None = None
    raw: str | None = None
    installable: dict | None = None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise Reject(f"{path.name}: {e.__class__.__name__}") from e


def _is(v, *types) -> bool:
    return any(v is None if t is None else (isinstance(v, t) and not (t is int and isinstance(v, bool)))
               for t in types)


def _inbox_source(repo: Path, leg_id: str) -> tuple[bool, dict | None, str | None]:
    if leg_id.startswith("dispatch-"):
        return False, None, None
    p = repo / "inbox" / f"{leg_id}.json"
    if not p.is_file():
        return False, None, None
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    return (True, data, None) if isinstance(data, dict) else (True, None, text[:4096])


def _check_meta(m) -> dict:
    if not isinstance(m, dict):
        raise Reject("meta.json is not an object")
    full = m.get("full_name")
    lic = m.get("license")
    ok = (_is(m.get("id"), int) and isinstance(full, str) and FULL_RE.match(full)
          and m.get("html_url") == f"https://github.com/{full}"
          and _is(m.get("description"), str, None) and _is(m.get("language"), str, None)
          and _is(m.get("stargazers_count"), int)
          and (lic is None or (isinstance(lic, dict) and _is(lic.get("spdx_id"), str, None))))
    if not ok:
        raise Reject("meta.json has unexpected shape")
    return m


def _check_entry(repo: Path, rel, meta: dict) -> str | None:
    if rel is None:
        return None
    if not isinstance(rel, str) or not ENTRY_RE.match(rel):
        raise Reject("status.entry is not a library path")
    path = (repo / rel).resolve()
    if path.parent != (repo / "library").resolve() or not path.is_file():
        raise Reject("status.entry is outside library or missing")
    fm, _ = entry.read_entry(path)
    if "repo_id" in fm:
        if fm["repo_id"] != meta["id"]:
            raise Reject("status.entry belongs to another repo_id")
    elif path.stem != entry.slug(meta["full_name"]):
        raise Reject("status.entry does not match this repo")
    return rel


def load_leg(d: Path, repo: Path, cats: list[str]) -> Leg:
    leg_id = d.name[len(PREFIX):] if d.name.startswith(PREFIX) else ""
    if not ID_RE.match(leg_id):
        return Leg(id=None, status="failed", error=f"publish-reject: bad artifact name {d.name!r}")
    from_inbox, capture, raw = _inbox_source(repo, leg_id)
    leg = Leg(id=leg_id, status="failed", from_inbox=from_inbox, capture=capture, raw=raw)
    try:
        item = _read_json(d / "item.json")
        if not (isinstance(item, dict) and item.get("id") == leg_id
                and _is(item.get("capture"), dict, None) and _is(item.get("raw"), str, None)):
            raise Reject("item.json does not match the artifact id")
        st = _read_json(d / "status.json")
        if not (isinstance(st, dict) and st.get("status") in ("ok", "dedup", "failed")
                and _is(st.get("error"), str, None) and _is(st.get("repo_id"), int, None)
                and isinstance(st.get("diagram"), bool) and _is(st.get("rounds"), int)
                and _is(st.get("wall_s"), int) and _is(st.get("claude_exit"), int, None)):
            raise Reject("status.json has unexpected shape")
        if st["status"] == "failed":
            leg.error = st["error"] or "failed"
            return leg
        meta = _check_meta(_read_json(d / "meta.json"))
        if st["repo_id"] != meta["id"]:
            raise Reject("status.repo_id does not match meta.id")
        rel = _check_entry(repo, st.get("entry"), meta)
        if st["status"] == "dedup" and rel is None:
            raise Reject("dedup without an existing entry")
        if from_inbox:
            at = (capture or {}).get("captured_at")
            try:
                datetime.fromisoformat(at)
            except (TypeError, ValueError):
                leg.error = "capture: bad captured_at"
                return leg
        summary, svg, run = None, None, {}
        if st["status"] == "ok":
            text = (d / "summary.json").read_text(encoding="utf-8") if (d / "summary.json").is_file() else ""
            errs = validate.validate_summary(text, cats)
            if errs:
                raise Reject("summary.json: " + "; ".join(errs))
            summary = json.loads(text)
            if st["diagram"]:
                svg = (d / "diagram.svg").read_text(encoding="utf-8") if (d / "diagram.svg").is_file() else ""
                errs = validate.validate_svg(svg)
                if errs:
                    raise Reject("diagram.svg: " + "; ".join(errs[:3]))
            run = _read_json(d / "run.json")
            if not isinstance(run, dict):
                raise Reject("run.json is not an object")
            # Optional and advisory: a missing or malformed claim just means "not installable".
            if (d / "install.json").is_file():
                try:
                    leg.installable = detect.check(json.loads((d / "install.json").read_text(encoding="utf-8")))
                except (OSError, ValueError, UnicodeDecodeError):
                    leg.installable = None
    except Reject as e:
        leg.status, leg.error = "failed", f"publish-reject: {e}"
        return leg
    leg.status, leg.entry, leg.diagram = st["status"], rel, st["diagram"]
    leg.rounds, leg.wall_s, leg.meta, leg.summary, leg.svg, leg.run = (
        st["rounds"], st["wall_s"], meta, summary, svg, run)
    return leg


def _run_record(leg: Leg) -> dict:
    result = leg.run.get("result") if isinstance(leg.run.get("result"), dict) else {}
    usage = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    turns = result.get("num_turns")
    tools = leg.run.get("tools") if isinstance(leg.run.get("tools"), dict) else {}
    return {
        "model": next((k for k in usage if isinstance(k, str)), None),
        "turns": turns if _is(turns, int) else None,
        "wall_s": leg.wall_s,
        "rounds": leg.rounds,
        "deepwiki": tools.get("deepwiki") is True,
        "diagram": leg.svg is not None,
    }


def _seed_state(repo: Path, stems: set, now: str) -> None:
    """Entries captured as 'I already have this installed' start as 在用; never overwrites the owner's own marks."""
    path = repo / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"v": 1, "items": {}}
    except (OSError, ValueError, UnicodeDecodeError):
        return
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return
    added = [s for s in sorted(stems) if s not in items]
    for stem in added:
        items[stem] = {"tried": "在用", "install": False, "owned": True, "updated_at": now}
    if added:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _publish_group(repo: Path, legs: list[Leg], now: str) -> Leg:
    winner = min(legs, key=lambda l: (RANK[(l.status, l.svg is not None)], l.id))
    meta = winner.meta
    rel = next((l.entry for l in legs if l.entry), None)
    target = repo / rel if rel else repo / "library" / f"{entry.slug(meta['full_name'])}.md"
    prev_fm = entry.read_record(target) if target.exists() else {}
    user = entry.read_entry(target)[1] if target.exists() else None
    new = [entry.write_sighting(l.id, l.capture) for l in legs if l.from_inbox and l.capture]
    sightings = entry.merge_sightings(list(prev_fm.get("sightings") or []), new)
    target.parent.mkdir(parents=True, exist_ok=True)
    svg_path = target.with_suffix(".svg")
    if winner.status == "ok":
        fm = entry.build_frontmatter(meta, winner.summary, sightings, prev_fm or None, _run_record(winner), now=now,
                                     installable=winner.installable)
        if winner.svg is not None:
            svg_path.write_text(winner.svg, encoding="utf-8")
        elif svg_path.exists():
            svg_path.unlink()
        text = entry.render_entry(fm, winner.summary, svg_path.name if winner.svg is not None else None, user)
    else:
        fm = entry.build_frontmatter(meta, None, sightings, prev_fm, None, now=now)
        auto = entry.read_auto(target)
        text = entry.render_entry(fm, None, None, user, auto=auto if auto is not None else "\n")
    entry.write_entry_files(target, fm, text)
    if any(l.from_inbox and l.capture and l.capture.get("preset") == "installed" for l in legs):
        _seed_state(repo, {target.stem}, now)
    return winner


def _move_done(repo: Path, leg: Leg) -> None:
    src = repo / "inbox" / f"{leg.id}.json"
    if leg.from_inbox and src.exists():
        (repo / "inbox" / "done").mkdir(parents=True, exist_ok=True)
        src.rename(repo / "inbox" / "done" / src.name)


def _move_failed(repo: Path, leg: Leg, now: str) -> None:
    src = repo / "inbox" / f"{leg.id}.json"
    if not (leg.id and leg.from_inbox and src.exists()):
        return
    (repo / "inbox" / "failed").mkdir(parents=True, exist_ok=True)
    record = {"error": leg.error, "failed_at": now, "capture": leg.capture, "raw": leg.raw}
    (repo / "inbox" / "failed" / src.name).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    src.unlink()


def _load_taxonomy(repo: Path) -> list[dict]:
    path = repo / "taxonomy.yml"
    if not path.exists():
        taxonomy.write_default(path)
    return taxonomy.load_or_default(path)


def _missing_legs(repo: Path, items: list | None, seen: set) -> list[Leg]:
    """Planned items whose leg uploaded nothing (timeout, cancellation) still get filed."""
    out = []
    for it in items or []:
        iid = it.get("id") if isinstance(it, dict) else None
        if isinstance(iid, str) and ID_RE.match(iid) and iid not in seen:
            from_inbox, capture, raw = _inbox_source(repo, iid)
            out.append(Leg(id=iid, status="failed", error="pipeline: no artifact (job timed out or was cancelled)",
                           from_inbox=from_inbox, capture=capture, raw=raw))
    return out


def run(artifacts: Path, repo: Path, now: str | None = None, items: list | None = None) -> dict:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    cats = _load_taxonomy(repo)
    names = taxonomy.names(cats)
    dirs = sorted(d for d in Path(artifacts).iterdir() if d.is_dir()) if Path(artifacts).is_dir() else []
    legs = [load_leg(d, repo, names) for d in dirs]
    legs += _missing_legs(repo, items, {l.id for l in legs if l.id})
    groups: dict[int, list[Leg]] = {}
    for leg in legs:
        if leg.status in ("ok", "dedup"):
            groups.setdefault(leg.meta["id"], []).append(leg)
    counts = {"ok": 0, "dedup": 0, "failed": 0, "failed_ids": []}
    for group in groups.values():
        try:
            winner = _publish_group(repo, group, now)
        except (OSError, ValueError, KeyError, TypeError) as e:
            for leg in group:
                leg.status, leg.error = "failed", f"publish-error: {e.__class__.__name__}: {e}"
            continue
        counts[winner.status] += 1
        for leg in group:
            _move_done(repo, leg)
    for leg in legs:
        if leg.status == "failed":
            counts["failed"] += 1
            counts["failed_ids"].append(leg.id or "?")
            _move_failed(repo, leg, now)
    entries = index.collect(repo / "library") if (repo / "library").exists() else []
    (repo / "README.md").write_text(index.render_readme(entries, cats, today=now[:10]), encoding="utf-8")
    (repo / "index.json").write_text(index.render_index(entries), encoding="utf-8")
    return counts


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)


def commit(repo: Path, counts: dict) -> bool:
    paths = [p for p in ("library", "inbox", "README.md", "index.json", "taxonomy.yml", "state.json") if (repo / p).exists()]
    if paths:
        _git(repo, "add", "-A", "--", *paths)
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return False
    msg = f"repobox: {counts['ok']} analyzed, {counts['dedup']} sightings, {counts['failed']} failed"
    _git(repo, "-c", "user.name=github-actions[bot]",
         "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-q", "-m", msg)
    return True


def push_with_retry(repo: Path, attempts: int = 3) -> None:
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    for _ in range(attempts):
        if _git(repo, "push", "-q", "origin", f"HEAD:{branch}", check=False).returncode == 0:
            return
        pulled = _git(repo, "-c", "user.name=github-actions[bot]",
                      "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                      "pull", "-q", "--rebase", "origin", branch, check=False)
        if pulled.returncode != 0:
            _git(repo, "rebase", "--abort", check=False)
            raise RuntimeError(f"rebase onto origin/{branch} failed: {pulled.stderr.strip()[:300]}")
    raise RuntimeError(f"push still rejected after {attempts} attempts")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", type=Path, required=True)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--items", type=Path, help="the plan job's items JSON")
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args(argv)
    planned = None
    if args.items:
        try:
            planned = json.loads(args.items.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            planned = None
        if not isinstance(planned, list):
            planned = None
    counts = run(args.artifacts, args.repo, items=planned)
    if args.push and commit(args.repo, counts):
        push_with_retry(args.repo)
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
