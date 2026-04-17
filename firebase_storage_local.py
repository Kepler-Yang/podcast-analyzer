import firebase_admin
from firebase_admin import credentials, storage
from datetime import timedelta
import os
import sys

if not firebase_admin._apps:
    # 👇 自動判斷是雲端環境還是本地環境
    # 取得目前腳本所在的目錄，確保路徑正確
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
        print("   可從 Firebase Console → 專案設定 → 服務帳戶 → 產生新的私密金鑰 下載。\n")
        sys.exit(1)

    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(
        cred, {"storageBucket": "whisge-1683c.firebasestorage.app"}
    )


def url_to_storage_key(url):
    """
    將 URL 轉為 MD5 hash，作為 Firebase Storage 的路徑 key。
    同一個 URL 永遠會對應到同一個 key，跨 taskId 可復用。
    """
    import hashlib
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def upload_file_to_storage(local_path, cloud_path):
    """
    將檔案上傳至 Firebase Storage 並回傳下載網址
    :param local_path: 本地檔案的路徑 (例如: 'test_audio.mp3')
    :param cloud_path: 雲端上的完整路徑 (例如: 'transcripts/abc123/title.srt')
    """
    try:
        # 1. 取得儲存桶 (Bucket)
        bucket = storage.bucket()

        # 2. 定義在雲端上的檔名
        file_name = os.path.basename(local_path)
        blob = bucket.blob(cloud_path)

        # 3. 上傳檔案
        print(f"📤 正在上傳 {file_name} 到 Firebase Storage ({cloud_path})...")
        blob.upload_from_filename(local_path)

        # 4. 產生簽署網址 (Signed URL) - 設定有效期限為 100 年 (約等於永久)
        url = blob.generate_signed_url(expiration=timedelta(days=36500))

        print(f"✅ 上傳成功！")
        return url
    except Exception as e:
        print(f"❌ 上傳失敗: {e}")
        return None


def check_file_exists(cloud_path):
    """
    檢查 Firebase Storage 上的檔案是否存在
    :param cloud_path: 雲端上的完整路徑
    :return: True/False
    """
    try:
        bucket = storage.bucket()
        blob = bucket.blob(cloud_path)
        return blob.exists()
    except Exception as e:
        print(f"⚠️ 檢查雲端檔案失敗: {e}")
        return False


def find_file_in_storage(folder_prefix, extension=".srt"):
    """
    在 Firebase Storage 的指定資料夾中搜尋特定副檔名的檔案。
    用於快取檢查：因為檔名含 title，無法事先知道確切路徑。
    :param folder_prefix: 雲端資料夾前綴 (例如 'transcripts/abc123/')
    :param extension: 要搜尋的副檔名
    :return: 找到的第一個檔案的完整路徑，或 None
    """
    try:
        bucket = storage.bucket()
        blobs = list(bucket.list_blobs(prefix=folder_prefix))
        for blob in blobs:
            if blob.name.endswith(extension):
                print(f"🔍 在雲端找到快取檔案: {blob.name}")
                return blob.name
        return None
    except Exception as e:
        print(f"⚠️ 搜尋雲端檔案失敗: {e}")
        return None


def download_file_from_storage(cloud_path, local_path):
    """
    從 Firebase Storage 下載檔案到本地
    :param cloud_path: 雲端上的完整路徑
    :param local_path: 本地儲存路徑
    :return: 成功回傳 local_path，失敗回傳 None
    """
    try:
        bucket = storage.bucket()
        blob = bucket.blob(cloud_path)

        # 確保本地目錄存在
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        print(f"📥 正在從雲端下載: {cloud_path}...")
        blob.download_to_filename(local_path)
        print(f"✅ 下載完成: {local_path}")
        return local_path
    except Exception as e:
        print(f"❌ 下載失敗: {e}")
        return None


def get_signed_url(cloud_path):
    """
    取得雲端檔案的簽署下載網址 (不下載檔案)
    :param cloud_path: 雲端上的完整路徑
    :return: 簽署網址或 None
    """
    try:
        bucket = storage.bucket()
        blob = bucket.blob(cloud_path)
        if not blob.exists():
            return None
        return blob.generate_signed_url(expiration=timedelta(days=36500))
    except Exception as e:
        print(f"⚠️ 取得簽署網址失敗: {e}")
        return None


# --- 測試代碼 ---
if __name__ == "__main__":
    # 測試上傳你剛才下載成功的 test_audio.mp3
    test_file = "test_audio.mp3"
    if os.path.exists(test_file):
        download_url = upload_file_to_storage(test_file, "test/test_audio.mp3")
        print(f"🔗 你的檔案下載連結是:\n{download_url}")
    else:
        print(f"找不到檔案 {test_file}，請確認檔名是否正確。")
