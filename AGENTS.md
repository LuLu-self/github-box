# GitHub Box（fork of RepoBox）

## Project goal

把滑到的 GitHub 專案收進自己的私人 repo，由 GitHub Actions 用自己的 Claude 訂閱寫白話介紹與架構圖。個人自用，其他人 fork 自架；不做共用網站、不代管任何人的 token。

## Stack

- Language: Python 3（pipeline）、原生 ES modules（網頁，無 build、無第三方 JS）
- Framework: none；GitHub Actions reusable workflow + GitHub Pages
- Datastore: 使用者自己的私人 GitHub repo（`library/*.md|json|svg`、`index.json`）
- Build/run: 無 build；`web/` 直接部署到 Pages，`analyze.yml` 由收藏 repo 以 SHA 呼叫
- Test: `python3 -m unittest discover -s action/tests && node --test 'web/tests/*.test.mjs'`；
  e2e：`PW_CORE=<playwright-core 路徑> [PW_CHROME=<chrome 路徑>] node web/tests/e2e/gate.cjs`（另有 capture.cjs、read.cjs）

## File layout

- `web/` — 收藏頁（index.html + app.js）、閱讀頁（read.html + read.js）、`lib/` 共用模組
- `action/scripts/` — pipeline：驗證、寫條目、索引、publish；`action/prompts/` — 給 Claude 的提示詞
- `.github/workflows/analyze.yml` — reusable workflow（plan → analyze → publish）
- `.github/workflows/install.yml` + `action/scripts/install.py` — 確認安裝：state.json → marketplace.json、dist/*.zip、INSTALL.md
- `skill/github-box/SKILL.md` — 收藏庫自己的 skill 範本（install.py 填入收藏庫名稱）
- `docs/specs/repobox.md` — 需求與決策的權威來源；`docs/media/` — README 用圖

## Constraints

- 收藏 repo 呼叫 `analyze.yml` 一律釘 40 字元 SHA，永不 `@main`——它拿得到私人 repo 寫入權與 Claude token；改了 pipeline 要手動換 SHA 才生效，自己的 repobox-library 和公開的 repobox-library-template 兩處都要換
- analyze job 裡的 Claude 不給 Bash／shell——runner 上 bwrap 起不來，且讀的是不可信 repo；需要執行的檢查由 workflow 跑再 `--resume` 回饋
- 存 token 的網頁不載入任何第三方 JS
- 沒過白名單的 SVG 不可經任何 blob:/data:/img URL 曝光，只顯示 rejectedNotice
- 改 `web/app.js` 後 `gate.cjs` 必須通過

- Path-type constraints are mirrored in `kit.toml [protected]`; keep the two in sync (one glob per line).

## Conventions

- Conventional commits（`type(scope): 摘要`）；README 維持 zh-TW（`kit.toml readme_lang`）。
- GitHub Actions: top-level `permissions: contents: read`, raised per job only when needed.
- GitHub Actions: pin every `uses:` to a 40-character commit SHA with a trailing `# vX.Y.Z` comment.

## Where to look

- `docs/specs/repobox.md` — 需求與決策的權威來源
- `.github/workflows/analyze.yml` — pipeline（plan → analyze → publish）
- `action/prompts/` — 給 Claude 的提示詞
