# AI Podcast 分析助手 (WhisGe - 本地 GPU 加速版)

## 專案簡介
這是一個由前端網頁與 Python 後端交織而成的 Podcast / YouTube 音訊分析系統。
透過強大的影音提取器 (yt-dlp) 自動下載目標影片的語音或攔截既有字幕，接著使用本地的 **GPU 加速 OpenAI Whisper 模型** 進行快速文字轉錄，最終將極高精度的逐字稿交由 **Google Gemini 模型** 進行洞見分析、提取重點精華、並條列出相關發燒個股。

本分支專案為了解決原本架構中 YouTube 常見的機房 IP 封鎖與外部 API 限速，全面脫離了雲端與 Groq，打造出純種的 **Local First (本機優先)** 設計。

## 架構特點與檔案說明
- **前端 (`index-local.html`)**: 
  - 提供極簡操作的網頁介面。直接對談 Firebase 排程器，且實裝了巧妙的 `狀態暗號化 (pending_local)`，**確保本機前端送出的任務只會由本機後端接單**，與正在服役中的雲端 (Render) 伺服器和平共存、永不搶單。

- **大腦管家 (`main_local.py`)**: 
  - 任務排程、資料庫監聽、清理專家。內建**終極快取攔截機制**，一旦資料庫有過去成功分析過的紀錄，能達到 0 秒回傳 (0% 算力消耗)。它還將所有暫存任務推向 Windows 底層 Temp 資料夾，完全迴避了 VS Code Live Server 不斷重新整理的干擾。

- **處理引擎 (`processor_local.py`)**: 
  - **核心運算管線**：它採用聰明的預判下載與純淨的 PyTorch `openai-whisper` 生態。不再受限於 25MB 上傳門檻，捨棄了繁雜耗時的轉碼壓縮，保證讓本地顯示卡 (GPU) 完全釋放效能狂飆。最後並導入高強制性的 Prompting，逼迫 AI 撰寫出字正腔圓的台灣繁體中文。

- **儲存傳遞 (`firebase_storage_local.py`)**: 
  - 獨立封裝。將跑完的檔案 (.srt / .json) 安全且持久地掛載於 Firebase Cloud Storage 上，供前端點擊下載使用。

---

## 🛠️ 環境配置與啟動指南

### Step 1: 安裝運行環境
為確保 GPU 能被徹底調用，建議使用已裝妥 CUDA 之 Anaconda 或虛擬環境進行：
```powershell
pip install -r requirements.txt
```

### Step 2: 設置金鑰 (環境變數)
您必須自行準備兩把鑰匙，且 **絕對不可將它們推播上傳到 GitHub**：
1. **Google Gemini API**:
   將附贈的 `.env.example` 複製一份改名為 **`.env`**，填入您的 API Token。
2. **Firebase 最高權限鑰匙**:
   將附贈的 `serviceAccountKey.json.example` 複製一份改名為 **`serviceAccountKey.json`**，並確實驗證內容（這把鑰匙掌控了您從後端更動 Firestore 的權限）。

### Step 3: 一鍵啟動
1. 啟動後端待命：
```powershell
python main_local.py
```
2. 使用 VS Code Live Server 開啟 `index-local.html` 網頁。
貼上任意 YouTube 或 ApplePodcast 網址，體驗無限制的極速解析！

---

## 🛡️ 資安與 GitHub 提交建議 
1. `index-local.html`: 雖然含有 apiKey 參數，但那是前端初始化 Firebase App 用途 (屬於公開識別碼)，受到您的 Security Rules 去限制權限，因此**能安全上傳**。
2. `python 腳本群`: 所有的 `.py` 代碼目前已無寫死的私人 Key (原先存在的 Gemini Key 已被清除，全面掛載 env)，因此**能安全上傳**。
3. `requirements.txt, .example`: 皆**安全可上傳**。
4. **警告禁止上傳清單**：真正有資安疑慮的只有 `.env` 與 `serviceAccountKey.json`，請確認它們靜靜躺在 `.gitignore` 內。
