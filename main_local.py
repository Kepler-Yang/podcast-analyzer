import time
import os
import sys
import threading  # 👈 新增：多執行緒套件
import tempfile
from flask import Flask, request, jsonify  # 👈 新增：request, jsonify
from flask_cors import CORS  # 👈 新增：允許跨網域請求
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import FieldFilter
from processor_local import process_audio_pipeline, run_gemini_analysis, GEMINI_MODEL
from chat_Gemini_local import handle_chat_request # 👈 新增：外掛對話模組
from firebase_storage_local import (
    upload_file_to_storage,
    find_file_in_storage,
    download_file_from_storage,
    get_signed_url,
    url_to_storage_key,
)
import shutil  # 🚀 加入 shutil 用於刪除目錄

# ==========================================
# [一、 初始化與設定]
# ==========================================
print("🔄 正在初始化系統...")

# 初始化 Firebase Admin SDK (確保不會重複初始化)
if not firebase_admin._apps:
    # 👇 自動判斷是雲端環境還是本地環境
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cloud_key = "/etc/secrets/serviceAccountKey.json"
    local_key = os.path.join(base_dir, "serviceAccountKey.json")

    if os.path.exists(cloud_key):
        cred_path = cloud_key
    elif os.path.exists(local_key):
        cred_path = local_key
    else:
        print("\n🚨 找不到 serviceAccountKey.json！")
        print(f"   已搜尋: {local_key}")
        print("   請將 Firebase 服務帳戶金鑰檔案放置於上述路徑。")
        sys.exit(1)

    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(
        cred, {"storageBucket": "whisge-1683c.firebasestorage.app"}
    )

db = firestore.client()
print("✅ 系統初始化完成！")


# ==========================================
# [一.五、 啟動預檢]
# ==========================================
import threading

# ... (現有代碼)

def start_heartbeat():
    """定期更新心跳，讓前端知道後端在線"""
    def heartbeat_loop():
        print("💓 心跳服務已啟動")
        while True:
            try:
                db.collection("system_status").document("local_engine").set({
                    "last_seen": firestore.SERVER_TIMESTAMP,
                    "status": "online"
                })
            except Exception as e:
                print(f"⚠️ 心跳更新失敗: {e}")
            time.sleep(30)
    
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()

def preflight_check():
    """
    啟動時預先檢查所有必要的環境設定。
    未通過則直接終止程式，避免承接任務後才發現缺少關鍵設定。
    """
    print("\n🔍 正在執行環境預檢...")
    errors = []

    # 1. 檢查 serviceAccountKey.json
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_key = os.path.join(base_dir, "serviceAccountKey.json")
    cloud_key = "/etc/secrets/serviceAccountKey.json"
    if not os.path.exists(cloud_key) and not os.path.exists(local_key):
        errors.append(f"❌ 找不到 serviceAccountKey.json (已搜尋: {local_key})")
    else:
        print("   ✅ serviceAccountKey.json ... OK")

    # 2. 檢查 GEMINI_API_KEY
    from dotenv import load_dotenv
    load_dotenv(os.path.join(base_dir, ".env"))
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        errors.append("❌ 環境變數 GEMINI_API_KEY 未設定 (請檢查 .env 檔案)")
    else:
        # 顯示部分 key 供確認 (僅前 8 碼)
        print(f"   ✅ GEMINI_API_KEY ... OK ({api_key[:8]}...)")

    # 3. 結果判定
    if errors:
        print("\n🚨 環境預檢失敗！以下問題必須修正後才能啟動：")
        for e in errors:
            print(f"   {e}")
        sys.exit(1)

    print("✅ 環境預檢全部通過！\n")


# ==========================================
# [二、 核心任務處理邏輯]
# ==========================================
def handle_new_task(task_id, task_data):
    """
    處理單一任務的完整流程 (含三層快取檢查)
    """
    url = task_data.get("url")
    url_hash = url_to_storage_key(url)
    temp_dir = os.path.join(tempfile.gettempdir(), f"whisge_{url_hash}")
    task_success = False  # 旗標：只有全部成功才清理本地暫存

    print(f"\n[{time.strftime('%H:%M:%S')}] 🛠️ 開始處理任務 ID: {task_id}")
    print(f"🔗 目標網址: {url}")
    print(f"🔑 URL Hash: {url_hash}")

    # 雲端資料夾前綴 (基於 URL hash，跨 taskId 可復用)
    cloud_folder = f"transcripts/{url_hash}/"
    # 雲端路徑會在取得 title 後動態生成 (使用 safe_title 命名)
    srt_cloud_path = None
    json_cloud_path = None
    safe_title = None

    try:
        # Step 0: 將任務標記為處理中，避免重複執行
        db.collection("tasks").document(task_id).update({"status": "processing"})

        # =============================================
        # 🔵 Layer 1: Firestore 是否已有完整分析結果？
        # =============================================
        print("🔍 [Layer 1] 檢查 Firestore 是否已有完整分析紀錄...")
        existing_docs = (
            db.collection("transcripts")
            .where(filter=FieldFilter("originalUrl", "==", url))
            .limit(1)
            .get()
        )

        for doc in existing_docs:
            print(f"🎯 快取命中！找到既有分析紀錄 (ID: {doc.id})")

            # --- 核心修復：複製一份資料並掛上當前 taskId ---
            old_data = doc.to_dict()

            # 💡 [補強] 如果舊資料有 metadata，更新到當前的 tasks 讓預覽卡片能顯示
            if "metadata" in old_data:
                db.collection("tasks").document(task_id).update(
                    {
                        "metadata": old_data["metadata"],
                        "status_msg": "🎯 偵測到快取紀錄，正在秒速回傳中...",
                    }
                )

            new_transcript_data = old_data.copy()
            new_transcript_data["taskId"] = task_id  # 換成現在這個任務的 ID
            
            # 🚀 [優化] 保留原始分析時間，不要用 SERVER_TIMESTAMP 覆蓋
            if "timestamp" not in new_transcript_data:
                new_transcript_data["timestamp"] = firestore.SERVER_TIMESTAMP

            # 寫入一筆新的記錄到 transcripts 集合
            new_doc_ref = db.collection("transcripts").add(new_transcript_data)
            new_transcript_id = new_doc_ref[1].id

            # 更新任務狀態
            db.collection("tasks").document(task_id).update(
                {"status": "completed", "transcriptId": new_transcript_id}
            )
            print(f"✅ 已同步快取內容至新任務 (Transcript ID: {new_transcript_id})")
            task_success = True
            return  # 結束

        print("   ❌ 無完整分析紀錄")

        # =============================================
        # 🟡 Layer 2: Firebase Storage 是否已有 SRT？
        # =============================================
        print("🔍 [Layer 2] 檢查 Firebase Storage 是否已有 SRT 逐字稿...")
        srt_content = None
        srt_url = None

        # 用前綴搜尋資料夾 (因為檔名含 title，無法事先知道確切路徑)
        found_srt_path = find_file_in_storage(cloud_folder, extension=".srt")

        if found_srt_path:
            print(f"🎯 雲端 SRT 快取命中！({found_srt_path})")
            srt_cloud_path = found_srt_path  # 記錄實際路徑
            os.makedirs(temp_dir, exist_ok=True)
            local_srt = os.path.join(temp_dir, os.path.basename(found_srt_path))
            download_file_from_storage(found_srt_path, local_srt)

            with open(local_srt, "r", encoding="utf-8") as f:
                srt_content = f.read()
            srt_url = get_signed_url(found_srt_path)

            # 嘗試取得 metadata 供前端預覽卡片 (輕量化 yt-dlp 呼叫)
            try:
                import yt_dlp
                db.collection("tasks").document(task_id).update(
                    {"status_msg": "🔎 正在取得影片資訊...", "progress": 15}
                )
                with yt_dlp.YoutubeDL({"quiet": True, "nocheckcertificate": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get("title", "未知標題")
                    from processor_local import get_safe_filename
                    safe_title = get_safe_filename(title)
                    duration_sec = info.get("duration", 0)
                    mins, secs = divmod(int(duration_sec), 60)
                    hrs, mins = divmod(mins, 60)
                    duration_text = (
                        f"{hrs:02d}:{mins:02d}:{secs:02d}"
                        if hrs > 0
                        else f"{mins:02d}:{secs:02d}"
                    )
                    uploader = (
                        info.get("series") or info.get("uploader")
                        or info.get("channel") or info.get("creator") or "未知頻道"
                    )
                    db.collection("tasks").document(task_id).update({
                        "metadata": {
                            "title": title,
                            "channel": uploader,
                            "duration": duration_sec,
                            "duration_text": duration_text,
                            "thumbnail": info.get("thumbnail", ""),
                        }
                    })
            except Exception as meta_e:
                print(f"⚠️ 取得 metadata 失敗 (不影響分析): {meta_e}")

            db.collection("tasks").document(task_id).update(
                {"status_msg": "🎯 已從雲端取得逐字稿，跳過下載與轉錄！", "progress": 75}
            )
        else:
            print("   ❌ 雲端無 SRT 快取")

        # =============================================
        # 🟠 Layer 3+4: 本地音檔快取 / 從頭下載
        # =============================================
        if not srt_content:
            print("🔍 [Layer 3/4] 啟動 Pipeline (含本地音檔快取檢查)...")
            # process_audio_pipeline 內部會自動檢查 temp_dir 是否已有音檔
            result = process_audio_pipeline(url, task_id=task_id, db=db, temp_dir=temp_dir)

            srt_content = result["srt_content"]
            local_srt = result["srt_path"]

            # 從 pipeline 結果取得 safe_title (pipeline 內部已用 get_safe_filename 處理)
            safe_title = os.path.splitext(os.path.basename(local_srt))[0]

            # 動態生成雲端路徑 (使用 title 命名，與雲端版一致)
            srt_cloud_path = f"{cloud_folder}{safe_title}.srt"

            # SRT 轉錄完成 → 立即上傳至 Firebase Storage (斷點續跑保障)
            print("☁️ SRT 轉錄完成，立即上傳至雲端備份...")
            srt_url = upload_file_to_storage(local_srt, srt_cloud_path)
            if not srt_url:
                print("⚠️ SRT 上傳失敗，但不影響後續 Gemini 分析")

        # =============================================
        # 🟣 Common: Gemini AI 分析
        # =============================================
        print("🧠 開始 Gemini AI 分析...")
        # JSON 檔名也使用 safe_title (與雲端版一致)
        json_filename = f"{safe_title}.json" if safe_title else "analysis.json"
        local_json = os.path.join(temp_dir, json_filename)
        json_cloud_path = f"{cloud_folder}{json_filename}"

        json_data = run_gemini_analysis(
            srt_content=srt_content,
            output_json_path=local_json,
            task_id=task_id,
            db=db,
        )

        # JSON 分析完成 → 上傳至 Firebase Storage
        print("☁️ JSON 分析完成，上傳至雲端...")
        json_url = upload_file_to_storage(local_json, json_cloud_path)
        if not json_url:
            print("⚠️ JSON 上傳失敗，嘗試取得既有簽署 URL...")
            json_url = get_signed_url(json_cloud_path) or "#"

        # =============================================
        # 🟢 寫入 Firestore 最終結果
        # =============================================
        # 重抓一次最新的 task 資料裡的 metadata (供快取復用)
        task_snap = db.collection("tasks").document(task_id).get()
        current_metadata = task_snap.to_dict().get("metadata", {})

        print("📝 將分析結果寫入資料庫...")
        transcript_data = {
            "taskId": task_id,
            "originalUrl": url,
            "title": json_data.get("title", "未知標題"),
            "investment_insight": json_data.get("investment_insight", ""),
            "highlights": json_data.get("highlights", []),
            "stocks": json_data.get("stocks", []),
            "sectors": json_data.get("sectors", []),
            "metadata": current_metadata,
            "srt_url": srt_url or "#",
            "json_url": json_url or "#",
            "timestamp": firestore.SERVER_TIMESTAMP,
        }

        # 將結果存入 'transcripts' 集合
        doc_ref = db.collection("transcripts").add(transcript_data)
        transcript_id = doc_ref[1].id
        print(f"✅ 資料庫更新成功！(Transcript ID: {transcript_id})")

        # 更新原始任務狀態為完成，並附上結果 ID
        db.collection("tasks").document(task_id).update(
            {"status": "completed", "transcriptId": transcript_id}
        )
        print(f"✨ 任務 {task_id} 圓滿結束！")
        task_success = True

    except Exception as e:
        error_msg = str(e)
        print(f"🚨 任務處理失敗: {error_msg}")
        # 將錯誤狀態寫回 Firebase，讓前端解除等待狀態
        db.collection("tasks").document(task_id).update(
            {
                "status": "failed",
                "error_msg": error_msg,
                "status_msg": "❌ 處理失敗，請檢查錯誤訊息",
            }
        )
    finally:
        # 🗑️ 只在「全部成功」時才清理本地暫存的音檔
        # 失敗時保留所有檔案，供下次斷點續跑
        if task_success and os.path.exists(temp_dir):
            print(f"🧹 任務成功，正在清理本地暫存目錄: {temp_dir}")
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"⚠️ 清理目錄失敗: {e}")
        elif not task_success:
            print(f"📁 任務未完成，保留本地暫存供下次續跑: {temp_dir}")


# ==========================================
# [三、 監聽器設定]
# ==========================================
def on_snapshot(col_snapshot, changes, read_time):
    """
    Firestore 變動監聽回呼函式
    """
    for change in changes:
        if change.type.name == "ADDED":
            data = change.document.to_dict()
            if data.get("status") == "pending_local":
                # 發現新任務，交給處理函式
                handle_new_task(change.document.id, data)


# ==========================================
# [四、 Web Service 偽裝與 API 端點]
# ==========================================
# 建立一個輕量的 Flask 網頁應用程式
app = Flask(__name__)
CORS(app)  # 允許跨網域，讓本地 HTML 可以 fetch

@app.route("/")
def home():
    # 當有人連線到這個網址時，顯示這段文字證明我們活著
    return "🚀 Podcast Analyzer Local Backend is Alive and Running!"

@app.route("/chat", methods=["POST"])
def chat_with_gemini():
    """將對話請求交給專屬模組處理"""
    return handle_chat_request(db, request.get_json())


def run_server():
    # Render 會動態分配一個 PORT 環境變數，我們必須監聽這個 Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    # 🔍 啟動預檢：確認所有必要的環境設定
    preflight_check()

    # 👉 啟動 Firestore 心跳服務 (讓前端能偵測後端是否在線)
    start_heartbeat()

    print("\n📡 系統已啟動，正在背景監聽新任務...")

    # 👉 啟動 Flask 網頁伺服器 (放在獨立的執行緒中，才不會卡住後面的監聽器)
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()

    # 👉 啟動 Firebase 監聽器
    def start_watch():
        query = db.collection("tasks").where(
            filter=FieldFilter("status", "==", "pending_local")
        )
        return query.on_snapshot(on_snapshot)

    query_watch = start_watch()

    try:
        while True:
            # 每 60 秒檢查監聽器是否還在運行
            time.sleep(60)
            if not query_watch or not query_watch.is_active:
                print("⚠️ 偵測到監聽器失效，重新啟動中...")
                query_watch = start_watch()
    except KeyboardInterrupt:
        if query_watch:
            query_watch.close()
        print("\n🛑 收到中斷指令，系統已停止監聽。")
