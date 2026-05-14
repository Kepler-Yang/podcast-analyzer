# WhisGe (Whisper + Gemini) - AI Podcast 分析助手 (雲端前端)

## 專案簡介
WhisGe 是一款結合了 **Whisper 語音辨識** 與 **Google Gemini AI** 的全方位 Podcast 分析工具。本專案為 **雲端前端 (Cloud Frontend)** 版本，主要負責提供使用者介面，並採用無伺服器 (Serverless) 架構直接與 Firebase 互動。使用者可在此提交音訊網址，實時監聽分析進度，並與 AI 進行深度對話。

## 使用方式
1. 開啟部署好的前端網頁 (如 GitHub Pages 或 Firebase Hosting 連結)。
2. 在輸入框中貼上 Apple Podcast 或 YouTube 網址。
3. 點擊「執行分析」，網頁將顯示進度條並等待後端處理。
4. 分析完成後，畫面將呈現財經洞察、亮點時間軸與提及個股。
5. 點擊右下角懸浮按鈕可啟動「Gemini 大腦助手」，針對當集內容進行問答。

## 主要功能
1. **無伺服器架構**：完全依賴前端 JavaScript 與 Firebase Client SDK 互動，輕量且快速。
2. **即時狀態監聽**：透過 Firestore `onSnapshot` 即時顯示後端處理進度 (從排隊、下載到分析)。
3. **動態對話介面**：內建精美的 Chat UI，支援與 Gemini 進行上下文關聯的連續問答。
4. **演示模式 (Demo Mode)**：輸入 `TEST` 即可載入本地的 `preview.json`，快速展示介面與對話功能。

## 快速啟動
### 1. 環境準備
- 任何現代化瀏覽器 (Chrome, Edge, Safari)。
- 網頁伺服器擴充功能 (如 VS Code 的 Live Server)。

### 2. 密鑰配置
- 本專案 Firebase 設定已內建於 `index.html` 中的 `firebaseConfig` 變數。若需連線至自有環境，請修改對應之 Config。

### 3. 啟動伺服器
- 使用 Live Server 直接開啟 `index.html` 即可開始使用。
