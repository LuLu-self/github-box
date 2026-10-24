"""Detect whether a cloned repo can be installed into Claude: a plugin marketplace, a plugin, or bare skills.

CLI: detect.py <target dir>  -> one JSON object (or null) on stdout

Runs on the untrusted checkout before .claude/ is stripped, and only looks at file names, never contents.
publish.py re-validates the result with check(), so this output is a claim, not a fact.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

KINDS = ("marketplace", "plugin", "skill")
SKILL_DIR_RE = re.compile(r"^(?:\.|(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]{1,200})$")
MAX_SKILLS = 20
MAX_DEPTH = 5
SKIP = {".git", "node_modules", "vendor", "dist", "build", "__pycache__"}


def detect(target: Path) -> dict | None:
    target = Path(target)
    if (target / ".claude-plugin" / "marketplace.json").is_file():
        return {"kind": "marketplace", "skills": []}
    if (target / ".claude-plugin" / "plugin.json").is_file():
        return {"kind": "plugin", "skills": []}
    skills = []
    for root, dirs, files in os.walk(target):
        rel = Path(root).relative_to(target)
        depth = len(rel.parts)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and depth < MAX_DEPTH)
        if "SKILL.md" in files:
            path = rel.as_posix()
            if SKILL_DIR_RE.match(path):
                skills.append(path)
            if len(skills) >= MAX_SKILLS:
                break
    return {"kind": "skill", "skills": sorted(skills)} if skills else None


def check(data) -> dict | None:
    """Fail-closed shape check used by publish; anything off means 'not installable'."""
    if not (isinstance(data, dict) and set(data) == {"kind", "skills"} and data["kind"] in KINDS
            and isinstance(data["skills"], list) and len(data["skills"]) <= MAX_SKILLS
            and all(isinstance(s, str) and SKILL_DIR_RE.match(s) for s in data["skills"])):
        return None
    if data["kind"] == "skill" and not data["skills"]:
        return None
    return {"kind": data["kind"], "skills": list(data["skills"])}


def main(argv: list[str]) -> int:
    print(json.dumps(detect(Path(argv[0])), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
