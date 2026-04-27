# Changelog - WhisGe (Local Version)

All notable changes to this project will be documented in this file.

## [2026-04-28] - 核心邏輯重構與對齊

### Added
- **UI 優化**：`index-local.html` 加入「單集網址」提示與引導文字，提升解析成功率。
- **解析增強**：`processor_local.py` 加入 `extract_flat` 與 User-Agent 偽裝，支援 Apple Podcast 節目頁面自動選取。
- **空值保護**：針對 `yt-dlp` 解析失敗加入 `if not info` 保護，避免 NoneType 報錯。

### Changed
- **ID 歸一化**：全面對齊 `transcripts` 集合 ID 為網址 MD5 (`url_hash`)，解決資料重複問題。
- **檔案重構**：將 `stocklist.json` 從 `scratch/` 搬移至專案根目錄，解決 Git 忽略導致的部署問題。

### Fixed
- **回傳型別修復**：修正 `load_stock_reference` 在根目錄讀取後的回傳格式，確保與 `task_handler_local` 的 Unpacking 邏輯相容。
