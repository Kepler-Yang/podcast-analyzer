import os
import time
import shutil
import tempfile
from google.cloud.firestore import FieldFilter, SERVER_TIMESTAMP
from config_local import db
from processor_local import process_audio_pipeline, run_gemini_analysis, get_safe_filename
from firebase_storage_local import (
    upload_file_to_storage,
    find_file_in_storage,
    download_file_from_storage,
    get_signed_url,
    url_to_storage_key,
)

# ==========================================
# [標記：T01] 核心任務調度邏輯 (Task Engine)
# ==========================================

def handle_new_task(task_id, task_data):
    """
    處理單一 Podcast 任務的完整流程 (含四層快取檢查與分析階段)。
    :param task_id: Firestore 上的文檔 ID
    :param task_data: 從 Firestore 讀取的文檔內容
    """
    url = task_data.get("url")
    url_hash = url_to_storage_key(url)
    temp_dir = os.path.join(tempfile.gettempdir(), f"whisge_{url_hash}")
    task_success = False  # 旗標：確保流程圓滿完成才清理暫存

    print(f"\n[{time.strftime('%H:%M:%S')}] 🛠️ 開始處理任務 ID: {task_id}")
    print(f"🔗 目標網址: {url}")

    # 定義雲端存放路徑前綴
    cloud_folder = f"transcripts/{url_hash}/"
    srt_cloud_path = None
    json_cloud_path = None
    safe_title = None

    try:
        # T01-1: 狀態更新 (避免重複領取任務)
        db.collection("tasks").document(task_id).update({"status": "processing"})

        # =============================================
        # 🎯 Layer 1: Firestore 全域快取檢查 (改用 ID 直接查詢)
        # =============================================
        print("🔍 [Layer 1] 檢查 Firestore 是否已有分析紀錄...")
        doc_snap = db.collection("transcripts").document(url_hash).get()

        if doc_snap.exists:
            print(f"🎯 快取命中！正在同步資料 (ID: {url_hash})...")
            transcript_id = url_hash
            
            # 更新 metadata 讓前端 UI 能顯示預覽卡片
            old_data = doc_snap.to_dict()
            if "metadata" in old_data:
                db.collection("tasks").document(task_id).update({
                    "metadata": old_data["metadata"],
                    "status_msg": "🔍 偵測到已有分析紀錄，正在同步中...",
                    "progress": 95
                })

            # 直接將既有的 transcriptId 關聯至當前任務
            db.collection("tasks").document(task_id).update({
                "status": "completed",
                "transcriptId": transcript_id
            })
            print(f"✅ 快取關聯完成 (Transcript ID: {transcript_id})")
            task_success = True
            return

        # =============================================
        # 🎯 Layer 2: Storage SRT 檔案快取檢查
        # =============================================
        print("🔍 [Layer 2] 檢查 Firebase Storage 快取檔案...")
        srt_content = None
        srt_url = None

        found_srt_path = find_file_in_storage(cloud_folder, extension=".srt")
        if found_srt_path:
            print(f"🎯 Storage 快取命中！({found_srt_path})")
            srt_cloud_path = found_srt_path
            os.makedirs(temp_dir, exist_ok=True)
            local_srt = os.path.join(temp_dir, os.path.basename(found_srt_path))
            
            # 從雲端拉回本地
            download_file_from_storage(found_srt_path, local_srt)
            with open(local_srt, "r", encoding="utf-8") as f:
                srt_content = f.read()
            srt_url = get_signed_url(found_srt_path)

            # 更新任務狀態提示
            db.collection("tasks").document(task_id).update({
                "status_msg": "🎨 [2/5] 已從雲端取得逐字稿，跳過算力消耗環節！",
                "progress": 70
            })
            
            # 輔助：嘗試補齊 metadata (不影響主流程)
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    safe_title = get_safe_filename(info.get("title", "未知"))
                    
                    # 同步更新 metadata 確保卡片顯示
                    duration_sec = info.get("duration", 0)
                    mins, secs = divmod(int(duration_sec), 60)
                    hrs, mins = divmod(mins, 60)
                    duration_text = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
                    uploader = info.get("series") or info.get("uploader") or info.get("channel") or "未知頻道"
                    
                    db.collection("tasks").document(task_id).update({
                        "metadata": {
                            "title": info.get("title", "未知標題"),
                            "channel": uploader,
                            "duration": duration_sec,
                            "duration_text": duration_text,
                            "thumbnail": info.get("thumbnail", ""),
                        }
                    })
            except: pass
        else:
            # =============================================
            # 🎯 Layer 3+4: 本地 Pipeline 執行 (下載 + Whisper)
            # =============================================
            print("🚀 [Layer 3/4] 啟動本地運算管線...")
            result = process_audio_pipeline(url, task_id=task_id, db=db, temp_dir=temp_dir)
            srt_content = result["srt_content"]
            local_srt = result["srt_path"]
            safe_title = os.path.splitext(os.path.basename(local_srt))[0]
            
            # 備份到雲端 (保障斷點續跑)
            srt_cloud_path = f"{cloud_folder}{safe_title}.srt"
            srt_url = upload_file_to_storage(local_srt, srt_cloud_path)

        # =============================================
        # 🟣 常規階段: Gemini AI 摘要分析
        # =============================================
        print("🧠 開始 AI 摘要分析...")
        json_filename = f"{safe_title}.json" if safe_title else "analysis.json"
        local_json = os.path.join(temp_dir, json_filename)
        json_cloud_path = f"{cloud_folder}{json_filename}"

        json_data = run_gemini_analysis(
            srt_content=srt_content,
            output_json_path=local_json,
            task_id=task_id,
            db=db,
        )

        # 上傳 JSON 結果
        json_url = upload_file_to_storage(local_json, json_cloud_path)

        # 寫入前最後更新進度
        db.collection("tasks").document(task_id).update({
            "status_msg": "📊 [5/5] 正在整理最後結果並存入雲端... (即將完成)",
            "progress": 95
        })

        # =============================================
        # 🟢 最終紀錄回寫 (Firestore)
        # =============================================
        task_snap = db.collection("tasks").document(task_id).get()
        current_metadata = task_snap.to_dict().get("metadata", {})

        # 🟢 最終紀錄回寫 (Firestore) - 使用 url_hash 作為唯一 ID
        # =============================================
        task_snap = db.collection("tasks").document(task_id).get()
        current_metadata = task_snap.to_dict().get("metadata", {})

        transcript_data = {
            "originalUrl": url,
            "title": json_data.get("title", "未知標題"),
            "investment_insight": json_data.get("investment_insight", ""),
            "highlights": json_data.get("highlights", []),
            "stocks": json_data.get("stocks", []),
            "sectors": json_data.get("sectors", []),
            "metadata": current_metadata,
            "srt_url": srt_url or "#",
            "json_url": json_url or "#",
            "timestamp": SERVER_TIMESTAMP,
        }

        # 使用 url_hash 作為文檔 ID，確保同網址僅存一筆，若存在則合併更新
        db.collection("transcripts").document(url_hash).set(transcript_data, merge=True)
        
        db.collection("tasks").document(task_id).update({
            "status": "completed",
            "transcriptId": url_hash
        })
        print(f"✨ 任務處理成功！ (ID: {task_id}, Transcript: {url_hash})")
        task_success = True

    except Exception as e:
        err_msg = str(e)
        print(f"🚨 任務異常中斷: {err_msg}")
        db.collection("tasks").document(task_id).update({
            "status": "failed",
            "error_msg": err_msg,
            "status_msg": "❌ 分析中斷，請稍後重試"
        })
    finally:
        # 若成功，才清理暫存；失敗則保留，以便下次觸發時能斷點續跑
        if task_success and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("🧹 本地暫存檔案已清理")

# ==========================================
# [標記：T02] Firebase 變動監聽回呼
# ==========================================
def on_snapshot(col_snapshot, changes, read_time):
    """Firestore 新任務監聽器的回呼介面"""
    for change in changes:
        if change.type.name == "ADDED":
            data = change.document.to_dict()
            if data.get("status") == "pending_local":
                handle_new_task(change.document.id, data)
