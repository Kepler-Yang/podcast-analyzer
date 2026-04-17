import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore, storage
from dotenv import load_dotenv

# ==========================================
# [標記：CF01] 全局設定與環境初始化
# ==========================================

# 1. 載入 .env 檔案
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# 2. 定義全局常量 (SSOT: Single Source of Truth)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
STORAGE_BUCKET = "whisge-1683c.firebasestorage.app"

# 3. Firebase 初始化邏輯
def initialize_firebase():
    """
    初始化 Firebase Admin SDK，自動判斷本地或雲端環境。
    :return: firestore_client, storage_bucket
    """
    if not firebase_admin._apps:
        print("🔄 正在初始化 Firebase 服務...")
        
        # 路徑判斷
        cloud_key = "/etc/secrets/serviceAccountKey.json"
        local_key = os.path.join(BASE_DIR, "serviceAccountKey.json")

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
        firebase_admin.initialize_app(cred, {
            "storageBucket": STORAGE_BUCKET
        })
        print("✅ Firebase 初始化完成")

    return firestore.client(), storage.bucket()

# 導出全局實例供其他模組使用
db, bucket = initialize_firebase()
