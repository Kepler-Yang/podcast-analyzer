# Changelog - WhisGe (Local Version)

All notable changes to this project will be documented in this file.

## [2026-04-28] - SRT 精準校對與非同步優化 (v1.3.0)

### Added
- **SRT 全文精準校對**：利用 Gemini 進行分段式校正，自動修復 Whisper 產出的同音異字（如：台機電 -> 台積電）。
- **非同步處理機制**：將 SRT 校對移至背景線程 (Background Thread)，讓使用者優先看到心得，不被校對時間阻塞。
- **批量修復工具 (`scratch/bulk_srt_fix.py`)**：支援對歷史紀錄進行一鍵式的全文校正補完。
- **校對狀態標記**：為 transcripts 紀錄增加 `srt_corrected` 欄位，確保資料處理狀態透明。

### Improved
- **校對精準度**：將 `stocklist.json` 整合進校正 Prompt，確保財經專業術語 100% 正確。
- **穩定性優化**：修復了大量資料查詢時的 Firestore Timeout 問題。

## [2026-04-28] - 核心邏輯重構與對齊 (v1.2.0)

### Added
- **UI 優化**：`index-local.html` 加入「單集網址」提示與引導文字，提升解析成功率。
- **解析增強**：`processor_local.py` 加入 `extract_flat` 與 User-Agent 偽裝，支援 Apple Podcast 節目頁面自動選取。
- **空值保護**：針對 `yt-dlp` 解析失敗加入 `if not info` 保護，避免 NoneType 報錯。

### Changed
- **ID 歸一化**：全面對齊 `transcripts` 集合 ID 為網址 MD5 (`url_hash`)，解決資料重複問題。
- **檔案重構**：將 `stocklist.json` 從 `scratch/` 搬移至專案根目錄，解決 Git 忽略導致的部署問題。

### Fixed
- **回傳型別修復**：修正 `load_stock_reference` 在根目錄讀取後的回傳格式，確保與 `task_handler_local` 的 Unpacking 邏輯相容。
