"""Owner profile and task areas for the analysis prompt, plus the activity facts from the GitHub API.

The profile lives in the library as profile.md (owner-written, trusted); TASK_AREAS is fixed so the
dashboard and the github-box skill can filter on it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

STALE_DAYS = 180
PROFILE_MAX = 4000
DEFAULT_PROFILE = "（未提供 profile.md）一般知識工作者；用平常會遇到的工作情境舉例。"

TASK_AREAS = [
    ("產品規劃與規格", "功能規劃、需求盤點、規格文件、流程圖"),
    ("跨部門溝通", "與研發、設計、業務對齊，會議與決策紀錄"),
    ("客戶服務與售前", "對客戶說明產品能力、處理客戶問題、售前售後"),
    ("AI 策略與 Agent", "AI 導入策略、Agent 產品設計與生命週期、對高層報告"),
    ("文件與簡報", "寫文件、做簡報、整理報告"),
    ("圖表與視覺化", "架構圖、流程圖、資料視覺化"),
    ("資料分析", "整理、分析、查詢資料"),
    ("開發與自動化", "寫程式、腳本、工作流自動化、Claude 外掛與 skill"),
    ("研究與學習", "蒐集資料、讀論文或文件、學新技術"),
    ("影音與內容", "影片、直播、字幕、社群內容"),
    ("個人效率", "筆記、時間管理、日常小工具"),
]


def area_names() -> list[str]:
    return [n for n, _ in TASK_AREAS]


def render_areas() -> str:
    return "\n".join(f"- {n}: {d}" for n, d in TASK_AREAS)


def load_profile(path: Path | None) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8").strip() if path else ""
    except (OSError, UnicodeDecodeError):
        text = ""
    return text[:PROFILE_MAX] or DEFAULT_PROFILE


def activity(meta: dict, now: datetime | None = None) -> dict:
    """pushed_at / archived straight from the API; stale = no push for more than STALE_DAYS."""
    now = now or datetime.now(timezone.utc)
    pushed = meta.get("pushed_at") if isinstance(meta.get("pushed_at"), str) else None
    days = None
    if pushed:
        try:
            days = (now - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
        except ValueError:
            pushed = None
    return {"pushed_at": pushed, "days_since_push": days, "stale": days is not None and days > STALE_DAYS,
            "archived": meta.get("archived") is True, "checked_at": now.isoformat(timespec="seconds")}


def render_activity(meta: dict) -> str:
    a = activity(meta)
    pushed = f"{a['pushed_at'][:10]}（{a['days_since_push']} 天前）" if a["pushed_at"] else "查不到（待查證）"
    return "\n".join([
        f"- 最後 push：{pushed}",
        f"- 超過 {STALE_DAYS} 天沒更新：{'是' if a['stale'] else '否'}",
        f"- 已封存（archived）：{'是' if a['archived'] else '否'}",
        f"- star：{meta.get('stargazers_count')}；open issues：{meta.get('open_issues_count')}",
    ])
