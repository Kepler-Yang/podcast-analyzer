import time
import os
import threading  # 👈 新增：多執行緒套件
import tempfile
from flask import Flask  # 👈 新增：輕量網頁框架
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import FieldFilter
from processor_local import process_audio_pipeline
from firebase_storage_local import upload_file_to_storage
import shutil # 🚀 加入 shutil 用於刪除目錄

# ==========================================
# [一、 初始化與設定]
# ==========================================
print("🔄 正在初始化系統...")

# 初始化 Firebase Admin SDK (確保不會重複初始化)
if not firebase_admin._apps:
    # 👇 自動判斷是雲端環境還是本地環境
    cred_path = (
        "/etc/secrets/serviceAccountKey.json"
        if os.path.exists("/etc/secrets/serviceAccountKey.json")
        else "serviceAccountKey.json"
    )
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(
        cred, {"storageBucket": "whisge-1683c.firebasestorage.app"}
    )

db = firestore.client()
print("✅ 系統初始化完成！")


# ==========================================
# [二、 核心任務處理邏輯]
# ==========================================
def handle_new_task(task_id, task_data):
    """
    處理單一任務的完整流程
    """
    url = task_data.get("url")
    print(f"\n[{time.strftime('%H:%M:%S')}] 🛠️ 開始處理任務 ID: {task_id}")
    print(f"🔗 目標網址: {url}")

    try:
        # Step 1: 將任務標記為處理中，避免重複執行
        db.collection("tasks").document(task_id).update({"status": "processing"})

        # ⚡⚡⚡ [修改後] 終極快取攔截機制 ⚡⚡⚡
        print("🔍 正在資料庫中尋找是否已有分析紀錄...")
        # 👇 使用 filter=FieldFilter(...) 包裝起來
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
            new_transcript_data["taskId"] = task_id  # 👈 換成現在這個任務的 ID
            new_transcript_data["timestamp"] = firestore.SERVER_TIMESTAMP  # 更新時間

            # 寫入一筆新的記錄到 transcripts 集合
            new_doc_ref = db.collection("transcripts").add(new_transcript_data)
            new_transcript_id = new_doc_ref[1].id

            # 更新任務狀態
            db.collection("tasks").document(task_id).update(
                {"status": "completed", "transcriptId": new_transcript_id}
            )
            print(f"✅ 已同步快取內容至新任務 (Transcript ID: {new_transcript_id})")
            return  # 結束

        print("❌ 無快取紀錄，準備啟動完整運算流程...")
        # ⚡⚡⚡ 快取攔截結束 ⚡⚡⚡

        # Step 2: 呼叫 Processor 進行下載、轉錄與 AI 分析
        print("⚙️ 將任務交由處理引擎 (Processor)...")
        # 接收傳回的 audio_path，並傳入 db 與 task_id 更新進度
        # 此處呼叫時 Processor 會在第一步更新 metadata 至 tasks 文檔
        srt_path, json_path, analysis_result, audio_path = process_audio_pipeline(
            url, task_id=task_id, db=db
        )

        # 為了以後快取能讀到 metadata，我們需要重抓一次最新的 task 資料裡的 metadata
        task_snap = db.collection("tasks").document(task_id).get()
        current_metadata = task_snap.to_dict().get("metadata", {})

        # Step 3: 將字幕檔 (.srt) 與 分析結果 (.json) 上傳至 Firebase Storage
        print(f"☁️ 準備上傳資源至雲端 (SRT: {os.path.basename(srt_path)}, JSON: {os.path.basename(json_path)})...")
        
        # 🚀 [優化]：上傳路徑包含標題檔名
        srt_cloud_path = f"transcripts/{task_id}/{os.path.basename(srt_path)}"
        json_cloud_path = f"transcripts/{task_id}/{os.path.basename(json_path)}"
        
        srt_url = upload_file_to_storage(srt_path, srt_cloud_path)
        json_url = upload_file_to_storage(json_path, json_cloud_path)

        if not srt_url or not json_url:
            raise Exception("❌ 資源檔案上傳至 Firebase Storage 失敗。")

        # Step 4: 將結果整併寫回 Firestore
        print("📝 將分析結果寫入資料庫...")
        transcript_data = {
            "taskId": task_id,
            "originalUrl": url,
            "title": analysis_result.get("title", "未知標題"),
            "investment_insight": analysis_result.get("investment_insight", ""),
            "highlights": analysis_result.get("highlights", []),
            "stocks": analysis_result.get("stocks", []),  # 👈 [新增] 提及個股
            "sectors": analysis_result.get("sectors", []),  # 👈 [新增] 產業族群
            "metadata": current_metadata,  # 👈 [新增] 存入 metadata，方便以後快取時讀取
            "srt_url": srt_url,
            "json_url": json_url,
            "timestamp": firestore.SERVER_TIMESTAMP,
        }

        # 將結果存入 'transcripts' 集合
        doc_ref = db.collection("transcripts").add(transcript_data)
        transcript_id = doc_ref[1].id
        print(f"✅ 資料庫更新成功！(Transcript ID: {transcript_id})")

        # Step 5: 更新原始任務狀態為完成，並附上結果 ID
        db.collection("tasks").document(task_id).update(
            {"status": "completed", "transcriptId": transcript_id}
        )
        print(f"✨ 任務 {task_id} 圓滿結束！")

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
        # 🗑️ [優化]：直接清除整個任務暫存資料夾
        temp_dir = os.path.join(tempfile.gettempdir(), f"whisge_temp_{task_id}")
        if os.path.exists(temp_dir):
            print(f"🧹 正在清理任務目錄: {temp_dir}")
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"⚠️ 清理目錄失敗: {e}")


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
# [四、 Web Service 偽裝與主程式進入點]
# ==========================================
# 建立一個輕量的 Flask 網頁應用程式
app = Flask(__name__)


@app.route("/")
def home():
    # 當有人連線到這個網址時，顯示這段文字證明我們活著
    return "🚀 Podcast Analyzer Backend is Alive and Running!"


def run_server():
    # Render 會動態分配一個 PORT 環境變數，我們必須監聽這個 Port
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
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
