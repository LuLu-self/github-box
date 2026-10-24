"""Validators for model output: summary.json schema and an SVG element/attribute allowlist.

CLI: validate.py summary <file> [--taxonomy <yml>] | validate.py svg <file>
Exit 0 with no output when valid; otherwise one error per line and exit 1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import profile
import taxonomy

CJK = re.compile(r"[一-鿿]")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,39}$")
STACK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+#/-]{0,29}$")
SUMMARY_KEYS = {"tagline", "intro", "examples", "requirements", "summary", "category", "tags", "stack", "highlights",
                "purpose", "scenarios", "sources", "verdict", "verdict_reason", "capabilities", "fit", "risks",
                "unverified", "tasks", "task_areas", "when_to_use", "how_to_use", "diagram_note", "diagram_nodes"}
NODE_KEYS = {"label", "zh", "role"}
VERDICTS = ("能用", "有條件才能用", "不建議用")


def _zh_list(v, lo: int, hi: int, min_len: int, max_len: int) -> bool:
    return (isinstance(v, list) and lo <= len(v) <= hi
            and all(isinstance(x, str) and min_len <= len(x) <= max_len and CJK.search(x) for x in v))
# Repo-relative paths the summary was written from; rendered as links back to the original files.
SOURCE_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]{1,200}$")
SVG_MAX_BYTES = 2 * 1024 * 1024

# Everything arch-blueprint's example and icon library use, plus a few harmless shape/text
# elements. No style, script, foreignObject, image or a: those are how SVG reaches the network.
SVG_ELEMENTS = {
    "svg", "title", "desc", "defs", "symbol", "g", "rect", "path", "line", "polyline",
    "polygon", "circle", "ellipse", "text", "tspan", "use", "marker",
}
SVG_ATTRS = {
    "aria-hidden", "aria-labelledby", "class", "cx", "cy", "d", "data-edge", "fill",
    "fill-opacity", "font-family", "font-size", "font-weight", "height", "href", "id",
    "letter-spacing", "marker-end", "marker-start", "markerHeight", "markerWidth", "orient",
    "points", "r", "refX", "refY", "role", "rx", "ry", "stroke", "stroke-dasharray",
    "stroke-linecap", "stroke-linejoin", "stroke-opacity", "stroke-width", "text-anchor",
    "transform", "viewBox", "width", "x", "x1", "x2", "y", "y1", "y2", "dominant-baseline",
    "opacity", "xmlns", "version",
}
INTERNAL_URL = r"url\(#[A-Za-z0-9_-]+\)"
# Exact grammars: a CSS escape such as "\75 rl(...)" can never match these.
STRICT = {
    "marker-start": re.compile(rf"^{INTERNAL_URL}$"),
    "marker-end": re.compile(rf"^{INTERNAL_URL}$"),
    "fill": re.compile(rf"^(none|transparent|currentColor|#[0-9A-Fa-f]{{3}}|#[0-9A-Fa-f]{{6}}|#[0-9A-Fa-f]{{8}}|{INTERNAL_URL})$"),
    "stroke": re.compile(rf"^(none|transparent|currentColor|#[0-9A-Fa-f]{{3}}|#[0-9A-Fa-f]{{6}}|#[0-9A-Fa-f]{{8}}|{INTERNAL_URL})$"),
}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def validate_summary(text: str, categories: list[str]) -> list[str]:
    try:
        data = json.loads(text)
    except ValueError as e:
        return [f"not a single JSON value: {e}"]
    if not isinstance(data, dict):
        return ["top level must be an object"]
    errors = []
    if set(data) != SUMMARY_KEYS:
        errors.append(f"keys must be exactly {sorted(SUMMARY_KEYS)}, got {sorted(data)}")
    tagline = data.get("tagline")
    if not (isinstance(tagline, str) and 4 <= len(tagline) <= 20 and CJK.search(tagline)):
        errors.append("tagline: 4-20 chars of plain Traditional Chinese")
    intro = data.get("intro")
    if not (isinstance(intro, str) and 30 <= len(intro) <= 300 and CJK.search(intro)):
        errors.append("intro: 30-300 chars of plain Traditional Chinese")
    ex = data.get("examples")
    if not (isinstance(ex, list) and 1 <= len(ex) <= 2
            and all(isinstance(e, str) and 10 <= len(e) <= 120 and CJK.search(e) for e in ex)):
        errors.append("examples: 1-2 Chinese sentences of 10-120 chars")
    req = data.get("requirements")
    if not (isinstance(req, list) and 1 <= len(req) <= 4
            and all(isinstance(r, str) and 2 <= len(r) <= 100 and CJK.search(r) for r in req)):
        errors.append("requirements: 1-4 Chinese lines of 2-100 chars")
    summary = data.get("summary")
    if not (isinstance(summary, str) and 20 <= len(summary) <= 600 and CJK.search(summary)):
        errors.append("summary: 20-600 chars with Traditional Chinese text")
    if data.get("category") not in categories:
        errors.append(f"category: must be one of {categories}")
    tags = data.get("tags")
    if not (isinstance(tags, list) and len(tags) <= 5
            and all(isinstance(t, str) and TAG_RE.match(t) for t in tags)):
        errors.append("tags: at most 5 lowercase tags")
    stack = data.get("stack")
    if not (isinstance(stack, list) and 1 <= len(stack) <= 8
            and all(isinstance(s, str) and STACK_RE.match(s) for s in stack)):
        errors.append("stack: 1-8 short names")
    hl = data.get("highlights")
    if not (isinstance(hl, list) and 2 <= len(hl) <= 3
            and all(isinstance(h, str) and 10 <= len(h) <= 120 and CJK.search(h) for h in hl)):
        errors.append("highlights: 2-3 Chinese sentences of 10-120 chars")
    purpose = data.get("purpose")
    if not (isinstance(purpose, str) and 6 <= len(purpose) <= 60 and CJK.search(purpose)):
        errors.append("purpose: 6-60 chars of plain Traditional Chinese")
    sc = data.get("scenarios")
    if not (isinstance(sc, list) and 1 <= len(sc) <= 3
            and all(isinstance(x, str) and 4 <= len(x) <= 60 and CJK.search(x) for x in sc)):
        errors.append("scenarios: 1-3 Chinese lines of 4-60 chars")
    src = data.get("sources")
    if not (isinstance(src, list) and 1 <= len(src) <= 6
            and all(isinstance(x, str) and SOURCE_RE.match(x) for x in src)):
        errors.append("sources: 1-6 repo-relative file paths (no leading /, no ..)")
    if data.get("verdict") not in VERDICTS:
        errors.append(f"verdict: must be one of {list(VERDICTS)}")
    vr = data.get("verdict_reason")
    if not (isinstance(vr, str) and 10 <= len(vr) <= 80 and CJK.search(vr)):
        errors.append("verdict_reason: 10-80 chars of plain Traditional Chinese")
    for key, lo, hi, mn, mx in (("capabilities", 1, 3, 10, 120), ("fit", 1, 2, 10, 150), ("risks", 1, 3, 6, 120),
                                ("unverified", 0, 3, 6, 100), ("tasks", 2, 5, 4, 30),
                                ("when_to_use", 1, 3, 6, 80), ("how_to_use", 1, 4, 6, 120)):
        if not _zh_list(data.get(key), lo, hi, mn, mx):
            errors.append(f"{key}: {lo}-{hi} Chinese lines of {mn}-{mx} chars")
    areas = data.get("task_areas")
    if not (isinstance(areas, list) and 1 <= len(areas) <= 3 and len(set(map(str, areas))) == len(areas)
            and all(a in profile.area_names() for a in areas)):
        errors.append(f"task_areas: 1-3 distinct names from {profile.area_names()}")
    note = data.get("diagram_note")
    if not (isinstance(note, str) and 20 <= len(note) <= 300 and CJK.search(note)):
        errors.append("diagram_note: 20-300 chars of plain Traditional Chinese")
    nodes = data.get("diagram_nodes")
    if not (isinstance(nodes, list) and 1 <= len(nodes) <= 16 and all(
            isinstance(n, dict) and set(n) == NODE_KEYS
            and isinstance(n["label"], str) and 1 <= len(n["label"].strip()) <= 40
            and isinstance(n["zh"], str) and 1 <= len(n["zh"]) <= 20 and CJK.search(n["zh"])
            and isinstance(n["role"], str) and 4 <= len(n["role"]) <= 60 and CJK.search(n["role"])
            for n in nodes)):
        errors.append("diagram_nodes: 1-16 objects {label 1-40, zh 1-20 Chinese, role 4-60 Chinese}")
    return errors


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def validate_svg(text: str) -> list[str]:
    if len(text.encode("utf-8")) > SVG_MAX_BYTES:
        return ["svg larger than 2 MiB"]
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return ["DOCTYPE/ENTITY not allowed"]
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    errors = []
    for el in root.iter():
        tag = _local(el.tag) if isinstance(el.tag, str) else "?"
        if tag not in SVG_ELEMENTS:
            errors.append(f"{tag}: element not allowed")
            continue
        for raw_name, value in el.attrib.items():
            name = _local(raw_name)
            low = value.strip().lower()
            if name.startswith("on") or name == "style":
                errors.append(f"{tag}@{name}: attribute not allowed")
            elif name not in SVG_ATTRS and not raw_name.startswith("{http://www.w3.org/2000/xmlns/}"):
                errors.append(f"{tag}@{name}: attribute not allowed")
            elif "\\" in value or CONTROL.search(value):
                errors.append(f"{tag}@{name}: escapes and control characters not allowed")
            elif name == "href" and not value.startswith("#"):
                errors.append(f"{tag}@{name}: only internal #references allowed")
            elif name in STRICT and not STRICT[name].match(value.strip()):
                errors.append(f"{tag}@{name}: value {value[:40]!r} not allowed")
            elif name not in STRICT and "url(" in low:
                errors.append(f"{tag}@{name}: url() not allowed here")
            elif "javascript:" in low or "data:" in low:
                errors.append(f"{tag}@{name}: script or data URI not allowed")
    return errors


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["summary", "svg"])
    ap.add_argument("file", type=Path)
    ap.add_argument("--taxonomy", type=Path)
    args = ap.parse_args(argv)
    try:
        text = args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"cannot read {args.file}: {e}")
        return 1
    if args.kind == "summary":
        errors = validate_summary(text, taxonomy.names(taxonomy.load_or_default(args.taxonomy)))
    else:
        errors = validate_svg(text)
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
