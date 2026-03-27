import firebase_admin
from firebase_admin import credentials, storage
from datetime import timedelta
import os

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


def upload_file_to_storage(local_path, cloud_folder="transcripts"):
    """
    將檔案上傳至 Firebase Storage 並回傳下載網址
    :param local_path: 本地檔案的路徑 (例如: 'test_audio.mp3')
    :param cloud_folder: 雲端上的資料夾名稱
    """
    try:
        # 1. 取得儲存桶 (Bucket)
        bucket = storage.bucket()

        # 2. 定義在雲端上的檔名 (保有原始檔名)
        file_name = os.path.basename(local_path)
        blob = bucket.blob(f"{cloud_folder}/{file_name}")

        # 3. 上傳檔案
        print(f"📤 正在上傳 {file_name} 到 Firebase Storage...")
        blob.upload_from_filename(local_path)

        # 4. 產生簽署網址 (Signed URL) - 設定有效期限為 100 年 (約等於永久)
        url = blob.generate_signed_url(expiration=timedelta(days=36500))

        print(f"✅ 上傳成功！")
        return url
    except Exception as e:
        print(f"❌ 上傳失敗: {e}")
        return None


# --- 測試代碼 ---
if __name__ == "__main__":
    # 測試上傳你剛才下載成功的 test_audio.mp3
    test_file = "test_audio.mp3"
    if os.path.exists(test_file):
        download_url = upload_file_to_storage(test_file)
        print(f"🔗 你的檔案下載連結是:\n{download_url}")
    else:
        print(f"找不到檔案 {test_file}，請確認檔名是否正確。")
