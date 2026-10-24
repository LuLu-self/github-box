"""Category list for the library: defaults, plus an optional user-editable taxonomy.yml."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,29}$")

DEFAULT: list[dict] = [
    {"name": "agent-framework", "definition": "建構或執行 AI agent 的框架、runtime 與 SDK"},
    {"name": "mcp-server", "definition": "提供 MCP 工具或資源給 agent 呼叫的伺服器"},
    {"name": "dev-tool", "definition": "開發者日常使用的 CLI、編輯器擴充、程式碼品質與工作流工具"},
    {"name": "model-inference", "definition": "模型推論、部署、量化、微調與評測"},
    {"name": "data-processing", "definition": "資料擷取、轉換、檢索、RAG 與向量資料處理"},
    {"name": "frontend", "definition": "網頁或桌面介面、UI 元件與前端應用"},
    {"name": "infrastructure", "definition": "部署、雲端、資料庫、監控與維運基礎設施"},
    {"name": "other", "definition": "不屬於以上分類的專案"},
]


def load(path: Path | None) -> list[dict]:
    if path is None or not Path(path).exists():
        return [dict(c) for c in DEFAULT]
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as e:
        raise ValueError(f"taxonomy.yml: cannot parse ({e.__class__.__name__})") from e
    raw = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("taxonomy.yml: 'categories' must be a non-empty list")
    cats, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"taxonomy.yml: bad entry {item!r}")
        name = item.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ValueError(f"taxonomy.yml: bad category name {name!r}")
        if name in seen:
            raise ValueError(f"taxonomy.yml: duplicate category {name!r}")
        seen.add(name)
        definition = item.get("definition") or ""
        cats.append({"name": name, "definition": str(definition)})
    return cats


def load_or_default(path: Path | None) -> list[dict]:
    """The user edits taxonomy.yml by hand; a broken file must not stop the pipeline."""
    try:
        return load(path)
    except ValueError as e:
        print(f"{e}; using the default categories", file=sys.stderr)
        return load(None)


def names(cats: list[dict]) -> list[str]:
    return [c["name"] for c in cats]


def write_default(path: Path) -> None:
    Path(path).write_text(
        yaml.safe_dump({"categories": DEFAULT}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def render_for_prompt(cats: list[dict]) -> str:
    return "\n".join(f"- {c['name']}: {c['definition']}" for c in cats)
