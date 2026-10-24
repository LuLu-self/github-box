"""Write the canonical 8-field status.json for one analyze leg.

Every status writer in the workflow goes through this script so publish can load all
artifacts with one fail-closed schema. Empty-string options mean null.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _opt_int(s: str | None) -> int | None:
    return int(s) if s not in (None, "") else None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--status", required=True, choices=["ok", "dedup", "failed"])
    ap.add_argument("--error", default="")
    ap.add_argument("--entry", default="")
    ap.add_argument("--repo-id", default="")
    ap.add_argument("--diagram", action="store_true")
    ap.add_argument("--rounds", default="0")
    ap.add_argument("--wall-s", default="0")
    ap.add_argument("--claude-exit", default="")
    a = ap.parse_args(argv)
    status = {
        "status": a.status,
        "error": a.error or None,
        "entry": a.entry or None,
        "repo_id": _opt_int(a.repo_id),
        "diagram": a.diagram,
        "rounds": _opt_int(a.rounds) or 0,
        "wall_s": _opt_int(a.wall_s) or 0,
        "claude_exit": _opt_int(a.claude_exit),
    }
    a.out.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
