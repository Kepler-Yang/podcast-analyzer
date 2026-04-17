import time
import threading
import sys
import os
from config_local import db
from task_handler_local import on_snapshot
from web_service_local import run_server
from google.cloud.firestore import FieldFilter, SERVER_TIMESTAMP

# ==========================================
# [標記：M01] WhisGe 本地後端啟動中樞
# ==========================================

def start_heartbeat():
    """M02: 啟動心跳服務，每 30 秒向 Firestore 更新在線狀態"""
    def heartbeat_loop():
        print("💓 心跳服務已啟動...")
        while True:
            try:
                db.collection("system_status").document("local_engine").set({
                    "last_seen": SERVER_TIMESTAMP,
                    "status": "online"
                })
            except Exception as e:
                print(f"⚠️ 心跳更新失敗: {e}")
            time.sleep(30)
    
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()

def preflight_check():
    """M03: 啟動環境預檢，確保 API Key 與 金鑰檔案 均已就緒"""
    print("\n🔍 正在執行啟動預檢...")
    
    # 檢查 .env
    if not os.environ.get("GEMINI_API_KEY"):
        print("🚨 錯誤：環境變數 GEMINI_API_KEY 未設定！")
        sys.exit(1)
        
    # 測試 Firestore 連通性
    try:
        db.collection("system_status").document("health_check").set({"last_ping": SERVER_TIMESTAMP})
        print("   ✅ Firebase 連線 ... OK")
    except Exception as e:
        print(f"🚨 錯誤：無法連線至 Firestore ({e})")
        sys.exit(1)

    print("✅ 環境預檢通過！\n")

if __name__ == "__main__":
    # 1. 執行環境檢查
    preflight_check()

    # 2. 啟動心跳監控 (背景線程)
    start_heartbeat()

    # 3. 啟動 Web API 伺服器 (背景線程)
    # 取自 web_service_local.py [標記：W01]
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # 4. 啟動任務監聽器 [標記：T02]
    print("📡 正在背景監聽 pending_local 任務...")
    query = db.collection("tasks").where(filter=FieldFilter("status", "==", "pending_local"))
    query_watch = query.on_snapshot(on_snapshot)

    # 5. 主執行緒防護
    try:
        while True:
            time.sleep(60)
            if not query_watch or not query_watch.is_active:
                print("⚠️ 監聽器失效，正在重新啟動...")
                query_watch = query.on_snapshot(on_snapshot)
    except KeyboardInterrupt:
        print("\n🛑 收到停止指令，系統關閉中。")
        if query_watch: query_watch.close()
