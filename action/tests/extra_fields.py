EXTRA = {
    "verdict": "有條件才能用",
    "verdict_reason": "功能符合但需要自備 ChatGPT 帳號",
    "capabilities": [
        "輸入 ChatGPT 對話指令，在本機讀寫檔案、執行指令，結果回到對話裡。"
    ],
    "fit": [
        "整理客戶回報的資料夾，把截圖依日期分類後給研發看。"
    ],
    "risks": [
        "會在本機執行指令，不適合放在公司正式電腦上。"
    ],
    "unverified": [
        "是否仍有人回覆 issue"
    ],
    "tasks": [
        "整理電腦檔案",
        "自動化重複操作"
    ],
    "task_areas": [
        "開發與自動化",
        "個人效率"
    ],
    "when_to_use": [
        "寫完規格要給研發看之前"
    ],
    "how_to_use": [
        "在 Claude Code 輸入 /tool 加上描述"
    ],
    "diagram_note": "使用者輸入指令後，由核心模組處理，再輸出成檔案給使用者。",
    "diagram_nodes": [
        {
            "label": "Core",
            "zh": "核心",
            "role": "處理使用者的指令"
        }
    ]
}
