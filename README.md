# WhisGe (Whisper + Gemini) - AI Podcast 分析助手

![Aesthetics](https://img.shields.io/badge/UI-Modern_Aesthetics-orange?style=for-the-badge)
![Tech](https://img.shields.io/badge/Tech-Python_|_Firebase_|_Gemini-blue?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Modular_Refactored-green?style=for-the-badge)

WhisGe 是一款結合了 **OpenAI Whisper (本地 GPU 加速)** 與 **Google Gemini AI** 的全方位 Podcast 分析工具。它能自動提取影音、轉錄逐字稿，並生成深度的財經投資洞察，同時提供互動式的 AI 對話體驗。

---

## 🏗️ 系統架構 (Modular Architecture)

我們在 2026 年 4 月完成了全面的後端架構重構，將功能徹底解耦，實現了 **High Cohesion, Low Coupling (高內聚、低耦合)** 的設計。

### 📂 目錄結構
```text
📦 WhisGe
 ┣ 📂 Local_Backend (Python)
 ┃ ┣ 📜 main_local.py             # [M] 啟動入口與環境預檢
 ┃ ┣ 📜 config_local.py           # [CF] 核心配置與 Firebase 初始化 (SSOT)
 ┃ ┣ 📜 task_handler_local.py     # [T] 任務調度引擎 (Layer 1-4 快取邏輯)
 ┃ ┣ 📜 web_service_local.py      # [W] API 伺服器 (Flask 路由端點)
 ┃ ┣ 📜 processor_local.py        # [P] 執行管線 (yt-dlp + Whisper + Gemini)
 ┃ ┣ 📜 firebase_storage_local.py # [F] 雲端儲存工具集
 ┃ ┗ 📜 chat_Gemini_local.py      # [C] 對話 Session 管理系統
 ┗ 📂 Frontend (HTML/JS)
   ┣ 📜 index-local.html          # 本地加速版介面
   ┣ 📜 index.html                # 雲端展示版介面 (Render/GitHub Pages)
   ┗ 📜 preview.json              # 模擬測試用資料
```

---

## 🏷️ 全端標註標準 (Labeling System)

為了極致的維護性，專案採用全端對稱的標籤標註系統，可根據標籤直接定位代碼區塊：

| 標籤前綴 | 負責領域 | 應用範例 |
| :--- | :--- | :--- |
| **Sxx** | **Structure** | HTML 介面結構 (S01-S09) |
| **Jxx** | **Javascript** | 前端邏輯控制 (J01-J14) |
| **Mxx** | **Main** | 後端啟動入口與預檢 |
| **Txx** | **Task** | 核心任務調度與快取邏輯 |
| **Pxx** | **Processor** | 影音下載與 AI 轉錄分析 |
| **Fxx** | **Firebase** | Firestore 與 Storage 存取工具 |
| **Wxx** | **Web** | API Server 與端點定義 |
| **Cxx** | **Chat** | AI 對話記憶與問答系統 |

---

## 🚀 核心特色

### 1. 四層快取機制 (Quadratic Cache)
實現「秒級回傳」的關鍵技術，系統會依序檢查：
- **Layer 1 (Firestore)**: 是否有完全相同的 URL 分析紀錄。
- **Layer 2 (Storage)**: 是否已有現成的 SRT 逐字稿檔案。
- **Layer 3 (Local Temp)**: 本地目錄是否已有下載好的音檔。
- **Layer 4 (Raw)**: 從頭下載、轉錄、分析 (最後手段)。

### 2. 本地 GPU 算力釋放
本地版 (`index-local.html` + `*_local.py`) 完美支持 CUDA 加速，無懼 YouTube 檔案大小限制，不佔用昂貴的雲端算力。

### 3. 高級 AI 對話互動
右下角懸浮按鈕啟動 **Gemini Chat**，AI 會以該集的逐字稿為背景知識，回答您的任何刁鑽問題。

---

## 🛠️ 快速啟動指南

### 環境準備
1. **Python 3.10+**: 建議使用 Anaconda。
2. **CUDA**: 若需 GPU 轉錄，需安裝正確的 NVIDIA 驅動。
3. **依賴安裝**: `pip install -r requirements.txt`

### 密鑰配置
- 在專案根目錄建立 `.env` 檔案並填入 `GEMINI_API_KEY=你的KEY`。
- 放置 `serviceAccountKey.json` 於根目錄以串接 Firebase。

### 啟動步驟
1. 執行後端機房：`python main_local.py`。
2. 開啟前端介面：瀏覽器打開 `index-local.html`。
3. 貼上網址，享受高速分析！

---

## 🛡️ 安全維護守則
- **`.env`** 與 **`serviceAccountKey.json`** 已加入 `.gitignore`，嚴禁提交至公有倉庫。
- 改動邏輯前，請參考代碼中的 `標記註解` 確保不影響其他模組。

---

© 2026 WhisGe Project | Designed for Efficiency and Aesthetics.
