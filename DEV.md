# 開發者指南 (DEV.md)

## 開發環境
- **作業系統**: Windows / Mac
- **前端技術**: HTML5, Vanilla JavaScript, CSS, TailwindCSS (CDN)
- **圖標庫**: Lucide Icons
- **後端服務依賴**: Firebase Firestore, Firebase Storage, WhisGe-backend

## 啟動方式
1. 確保已安裝 VS Code 及其擴充功能 `Live Server`。
2. 在 VS Code 中開啟 `index.html`。
3. 點擊右鍵選擇 `Open with Live Server`。
4. 瀏覽器將自動開啟 `http://127.0.0.1:5500/index.html`。

## API (Firebase 溝通)
本前端不提供傳統 REST API，而是透過 Firebase SDK 進行溝通：
- **寫入**: `addDoc` 至 `tasks` 集合，狀態設為 `pending`。
- **讀取**: `onSnapshot` 監聽 `tasks` 文件的進度與狀態變更。
- **讀取**: 當任務完成取得 `transcriptId` 後，透過 `onSnapshot` 讀取 `transcripts` 集合獲取完整分析結果。

## 資料流 (Data Flow)
1. **任務建立**：使用者點擊「執行分析」，JS 將網址與時間戳記寫入 `tasks` 集合，狀態為 `pending`。
2. **進度追蹤**：前端建立監聽器，當雲端後端接手時，狀態變更為 `processing`，前端同步更新進度條與訊息。
3. **結果接收**：當後端完成處理並寫入 `transcripts` 後，前端透過 `transcriptId` 取得資料並渲染 UI。
4. **AI 對話**：使用者發送訊息，前端透過 HTTP POST (若有設定 web_service) 或直接將訊息送至後端處理，再將 Gemini 回覆顯示於對話框中。

## 測試與驗證方式
- **UI 預覽測試**：在輸入框中輸入 `TEST`，系統將自動載入本地的 `preview.json`，可用於驗證 UI 排版與對話框動畫。
- **整合測試**：輸入一組真實的 YouTube 或 Apple Podcast 網址，並確認雲端後端 (WhisGe-backend) 已啟動。觀察 Firestore 的任務狀態變化以及進度條的動態更新。
