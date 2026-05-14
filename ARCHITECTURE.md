# 系統架構 (ARCHITECTURE.md)

## 目錄結構
```text
📦 WhisGe (Frontend)
 ┣ 📜 index.html                # 雲端版前端介面 (主程式)
 ┣ 📜 preview.json              # 模擬測試用資料
 ┣ 📜 README.md                 # 專案簡介與使用指南
 ┣ 📜 DEV.md                    # 開發者環境與資料流指南
 ┣ 📜 ARCHITECTURE.md           # 架構說明文件
 ┗ 📜 CHANGELOG.md              # 系統變更紀錄
```

## 模組責任
- **`index.html` (S01-S09 / J01-J12)**:
  - **視圖層 (View)**: 使用 TailwindCSS 建構響應式介面，包含導航欄、輸入區、進度條、分析結果卡片與對話視窗。
  - **邏輯層 (Controller)**: 處理使用者輸入驗證、觸發 Demo 模式 (`runDemoMode`)、控制 Modal 彈跳與對話框開關。
  - **資料層 (Model)**: 透過 Firebase SDK 直接寫入任務與訂閱結果，實踐無伺服器 (Serverless) 前端。
- **`preview.json`**: 提供預設的測試資料集，用於開發階段的 UI 除錯與展示。

## 前後端關係
本專案為**前端無伺服器 (Serverless-like)** 架構，擔任發號施令與結果呈現的角色：
1. **Frontend (`index.html`)**: 作為客戶端，將使用者的分析請求打包並推播至 Firestore 的 `tasks` 集合。
2. **Backend (`WhisGe-backend`)**: 隱身於雲端，負責認領 `pending` 狀態的任務並執行耗時運算。
3. **中繼站 (Firestore)**: 作為前後端唯一的溝通橋樑。前端僅透過監聽文件狀態變化來得知後端運作情形。

## 資料來源
- **輸入來源**: 使用者輸入之 YouTube 或 Podcast 網址、對話框文字。
- **資料庫 (Database)**: Google Cloud Firestore (`tasks` 與 `transcripts` 集合)。
- **外部資源**: 靜態載入的字型檔 (Noto Sans TC)、樣式庫 (Tailwind CDN)、圖標庫 (Lucide)。
