"""List the work items for one run: either the single dispatch URL, or every inbox/*.json.

CLI: items.py --inbox inbox --url "<dispatch url or empty>" --run-id N  -> one JSON line
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
URL_RE = re.compile(r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+/?$")
URL_MAX = 200
# GitHub caps a matrix at 256 jobs; the rest waits for the next run (any push or an empty dispatch).
MAX_ITEMS = 200


def _check_capture(cap: dict) -> str | None:
    if cap.get("v") != 1:
        return "capture: v must be 1"
    url = cap.get("url")
    if not isinstance(url, str) or len(url) > URL_MAX or not URL_RE.match(url):
        return "capture: url is not a GitHub repo URL"
    at = cap.get("captured_at")
    if not isinstance(at, str):
        return "capture: captured_at missing"
    try:
        datetime.fromisoformat(at)
    except ValueError:
        return "capture: captured_at is not ISO 8601"
    return None


def _item(path: Path) -> dict:
    """Matrix items carry only id/url/force: publish re-reads the capture from the repo."""
    stem = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError:
        return {"id": stem, "url": None, "force": False, "error": "capture: not valid JSON"}
    if not isinstance(data, dict):
        return {"id": stem, "url": None, "force": False, "error": "capture: not a JSON object"}
    err = _check_capture(data)
    if err:
        return {"id": stem, "url": None, "force": False, "error": err}
    return {"id": stem, "url": data["url"], "force": False}


def collect(inbox: Path, url: str, run_id: str) -> list[dict]:
    if url:
        return [{"id": f"dispatch-{run_id}", "url": url, "force": True}]
    out, skipped = [], []
    for p in sorted(Path(inbox).glob("*.json")):
        if not p.is_file():
            continue
        if not ID_RE.match(p.stem):
            skipped.append(p.name)
            continue
        out.append(_item(p))
    out.sort(key=lambda i: i["id"])
    if skipped or len(out) > MAX_ITEMS:
        print(json.dumps({"skipped": skipped, "deferred": len(out[MAX_ITEMS:])}), file=sys.stderr)
    return out[:MAX_ITEMS]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", type=Path, required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    print(json.dumps(collect(args.inbox, args.url.strip(), args.run_id), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
