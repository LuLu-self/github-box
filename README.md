# GitHub Box

我自己的 GitHub 收藏箱。在手機或電腦看到好的 GitHub 專案，分享或貼上連結，GitHub Actions 就用我的 Claude 訂閱自動寫：

- **能不能用**（能用／有條件才能用／不建議用）＋理由：照 find-skill「評估既有連結」的固定架構，對照 `profile.md` 裡我的工作情境判斷
- **活躍度**：最後更新時間、是否封存，由程式查 GitHub API，超過 180 天會標「半年未更新」
- **實際能力邊界**、**對你的應用場景（推論）**、**不適合的情況／風險（推論）**、**待查證**
- **可用在哪些任務**＋任務類型，Claude 開始任何任務前會先來這裡查
- **用途**、**適用情境**（方便之後搜尋）
- 白話介紹、**使用門檻**（平台、需要準備、費用、限制）
- 技術摘要、值得借鏡、架構圖
- **原始出處**：GitHub 首頁、摘要依據的檔案、在哪裡看到的貼文，方便回頭核對
- **相關收藏**：依分類、標籤、技術棧自動算出

已經裝過的 repo 也能收：看板一次貼多個連結並勾「這些我原本就裝了」，或在 Claude Code 對 Claude 說「把我裝過的外掛收進 GitHub Box」。

另外在看板上可以標記 **是否已試過**（未試／試過／在用／放棄），以及按 **確認安裝**：如果收藏的是 Claude 外掛或 skill，會自動加進 Claude Code 的套件清單，並打包成 Claude Chat／Cowork 可以上傳的 zip。

> 基於 [cholateio/repobox](https://github.com/cholateio/repobox)（MIT）修改。

## 架構

```
iPhone 分享（捷徑）／電腦書籤／看板貼上／對 Claude 說「收這個」
        │  寫入 inbox/<id>.json
        ▼
私人收藏庫 github-box-library ──► Actions（呼叫本 repo 的 analyze.yml，釘在固定 commit）
        │                              └─ Claude（你的訂閱 token，沒有 shell、只能寫暫存資料夾）
        │                              └─ 另一個不跑 AI 的步驟重新驗證後才寫入
        ▼
library/*.md|json|svg、index.json（含相關收藏）
        │
        ├─► 看板（本 repo 的 GitHub Pages，資料用你的 token 從私人 repo 讀）
        └─► 看板按「確認安裝」→ state.json → install.yml
                 ├─ .claude-plugin/marketplace.json  → Claude Code
                 └─ dist/*.zip                       → Claude Chat／Cowork
```

這個 repo 只放程式碼，是公開的（GitHub Pages 免費方案需要公開）；收藏內容都在私人的 `github-box-library`。

## 安裝（只做一次）

1. **看板**：這個 repo 的 Settings › Pages › Source 選 **GitHub Actions**，再到 Actions 手動跑一次 `pages`。看板在 `https://<帳號小寫>.github.io/github-box/`。
2. **Claude token**：在裝了 Claude Code 的電腦執行 `claude setup-token`，把印出的 token 存到 `github-box-library` 的 Settings › Secrets and variables › Actions，名稱 `CLAUDE_CODE_OAUTH_TOKEN`。
3. **看板用的 token**：GitHub › Settings › Developer settings › Fine-grained tokens，只選 `github-box-library`，權限 Contents：Read and write。在看板右上角設定裡貼上收藏庫名稱和這個 token。
4. **固定看板**：iPhone 用 Safari 打開看板 › 分享 › 加入主畫面。
5. **iPhone 分享捷徑**：捷徑 App › 新增捷徑：
   1. 開啟「在分享表單中顯示」，接收類型選 **URL** 和 **文字**
   2. 動作「URL 編碼」：編碼「捷徑輸入」
   3. 動作「文字」：貼上看板設定裡的 **iPhone 捷徑網址**，後面接上一步的「URL 編碼後的文字」
   4. 動作「打開 URL」：打開上一步的文字
   5. 捷徑命名為「收進 GitHub Box」

   之後在 Threads、Safari 按分享 › 收進 GitHub Box 就會收下（第一次請先在 Safari 打開看板並儲存設定）。
6. **電腦**：把看板設定裡的「收進 GitHub Box」按鈕拖到書籤列。

## 安裝到 Claude

- **Claude Code**：`/plugin marketplace add <帳號>/github-box-library`，再 `/plugin install github-box@github-box`。之後確認安裝的東西用 `/plugin marketplace update github-box` 和 `/plugin install <名稱>@github-box`；名稱都列在收藏庫的 `INSTALL.md`。
- **Claude Chat／Cowork**：claude.ai › 設定 › Capabilities › Skills 上傳 `dist/github-box.zip`（GitHub Box 本身）和各條目頁的 zip。

`github-box` skill 讓 Claude 能查你的收藏（例如「我收過哪些直播工具？」）、幫你收新連結、標記試過或確認安裝。需要 Claude 能存取 GitHub（Claude Code 的 `gh`、GitHub MCP，或 claude.ai 的 GitHub 連接器）。

## 調整分析方式

- 收藏庫的 `profile.md`：我的工作情境，AI 判斷「能不能用」和舉例時會參考，改了之後新的分析就會套用。
- 收藏庫的 `taxonomy.yml`：分類。
- 任務類型清單在本 repo 的 `action/scripts/profile.py`（`TASK_AREAS`）。
- 已經分析過的要重跑：收藏庫 Actions › analyze › Run workflow，填 repo 網址。

## 開發

```
python3 -m unittest discover -s action/tests
node --test 'web/tests/*.test.mjs'
PW_CORE=<playwright-core 路徑> node web/tests/e2e/gate.cjs
```

改了 `action/` 或 workflow 之後，要把收藏庫兩個 workflow 裡釘的 commit SHA 換成新的才會生效。

## 授權

[MIT](LICENSE)
