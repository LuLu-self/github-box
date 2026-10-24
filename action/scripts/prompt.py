"""Render the analyze / fix prompts from action/prompts/*.md with string.Template.

CLI: prompt.py analyze --full F --target T --out O --skill S --taxonomy <yml|-> [--meta meta.json] [--profile profile.md]
     prompt.py fix --out O --check <check.txt>
     prompt.py fix-summary --out O --errors <validator output>
"""
from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path

import profile
import taxonomy

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
ANALYZE = PROMPTS / "analyze.md"
FIX = PROMPTS / "fix.md"
FIX_SUMMARY = PROMPTS / "fix-summary.md"


def render(template: Path, **values: str) -> str:
    # substitute() is single-pass, so a "$OUT" inside checker output stays literal.
    return string.Template(template.read_text(encoding="utf-8")).substitute(**values)


def _meta(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError, UnicodeDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    a = sub.add_parser("analyze")
    for flag in ("--full", "--target", "--out", "--skill", "--taxonomy"):
        a.add_argument(flag, required=True)
    a.add_argument("--meta", default="")
    a.add_argument("--profile", default="")
    f = sub.add_parser("fix")
    f.add_argument("--out", required=True)
    f.add_argument("--check", required=True)
    fs = sub.add_parser("fix-summary")
    fs.add_argument("--out", required=True)
    fs.add_argument("--errors", required=True)
    args = ap.parse_args(argv)
    if args.kind == "analyze":
        cats = taxonomy.load_or_default(None if args.taxonomy == "-" else Path(args.taxonomy))
        text = render(ANALYZE, FULL=args.full, TARGET=args.target, OUT=args.out, SKILL=args.skill,
                      TAXONOMY=taxonomy.render_for_prompt(cats), TASK_AREAS=profile.render_areas(),
                      PROFILE=profile.load_profile(Path(args.profile) if args.profile else None),
                      ACTIVITY=profile.render_activity(_meta(args.meta)))
    elif args.kind == "fix":
        check = Path(args.check).read_text(encoding="utf-8", errors="replace")
        text = render(FIX, OUT=args.out, CHECK=check)
    else:
        errors = Path(args.errors).read_text(encoding="utf-8", errors="replace")
        text = render(FIX_SUMMARY, OUT=args.out, ERRORS=errors)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
