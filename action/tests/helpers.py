"""Builders shared by the index and publish tests."""
from pathlib import Path

import entry
from extra_fields import EXTRA

ANALYSIS = {
    "tagline": "測試用的一句白話副標",
    "intro": "一個給人用的白話介紹，說明這個工具能幫你做什麼事情，以及為什麼你會想用它。", "examples": ["用它來整理下載資料夾裡的檔案。", "用它來幫專案自動寫測試。"],
    "requirements": ["平台：只支援 Windows", "費用：免費"],
    "summary": "這是一個用來測試的專案，說明寫得夠長才會通過驗證。", "category": "dev-tool", "tags": ["cli", "test"],
    "stack": ["Python"], "highlights": ["第一個值得借鏡的地方。", "第二個值得借鏡的地方。"],
    "purpose": "整理電腦裡亂掉的檔案", "scenarios": ["下載資料夾塞滿的時候"], "sources": ["README.md", "src/main.py"],
    **EXTRA,
}


def meta(full="Owner/Repo", rid=1, **kw):
    m = {"id": rid, "full_name": full, "html_url": f"https://github.com/{full}", "description": "desc",
         "language": "Python", "stargazers_count": 3, "license": None}
    m.update(kw)
    return m


def write_entry(library: Path, full="Owner/Repo", rid=1, sightings=(), category="dev-tool", stem=None,
                svg=False, user=None, **meta_kw):
    library.mkdir(parents=True, exist_ok=True)
    stem = stem or entry.slug(full)
    fm = entry.build_frontmatter(meta(full, rid, **meta_kw), dict(ANALYSIS, category=category), list(sightings),
                                 None, None, now="2026-10-01T00:00:00+00:00")
    svg_name = f"{stem}.svg" if svg else None
    if svg:
        (library / svg_name).write_text("<svg/>", encoding="utf-8")
    path = library / f"{stem}.md"
    entry.write_entry_files(path, fm, entry.render_entry(fm, ANALYSIS, svg_name, user))
    return path
