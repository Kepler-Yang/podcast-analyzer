import os
from datetime import timedelta
from config_local import bucket

# ==========================================
# [標記：F01] 雲端存取工具集 (Storage Utils)
# ==========================================

def url_to_storage_key(url):
    """
    將 URL 轉為 MD5 hash，作為 Firebase Storage 的路徑 key。
    同一個 URL 永遠會對應到同一個 key，跨 taskId 可復用快取。
    """
    import hashlib
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def upload_file_to_storage(local_path, cloud_path):
    """
    將檔案上傳至 Firebase Storage 並回傳永久簽署網址。
    :param local_path: 本地原始路徑 (例如: 'audio.m4a')
    :param cloud_path: 雲端完整路徑 (例如: 'transcripts/abc/title.srt')
    :return: 公開存取網址或 None
    """
    try:
        file_name = os.path.basename(local_path)
        blob = bucket.blob(cloud_path)

        # 根據副檔名自定義 Content-Type (防文字檔預覽亂碼)
        content_type = None
        if local_path.lower().endswith(".srt"):
            content_type = "text/plain; charset=utf-8"
        elif local_path.lower().endswith(".json"):
            content_type = "application/json; charset=utf-8"

        print(f"📤 正在上傳 {file_name} 到 Firebase Storage...")
        blob.upload_from_filename(local_path, content_type=content_type)

        # 產生長期簽署網址 (有效期限設為約 100 年)
        url = blob.generate_signed_url(expiration=timedelta(days=36500))
        print(f"✅ 上傳成功")
        return url
    except Exception as e:
        print(f"❌ 上傳失敗: {e}")
        return None


def find_file_in_storage(folder_prefix, extension=".srt"):
    """
    在指定資料夾中搜尋含特定副檔名的第一個檔案 (快取攔截點)。
    :param folder_prefix: 例如 'transcripts/hash/'
    :param extension: 例如 '.srt'
    :return: 檔案雲端路徑或 None
    """
    try:
        blobs = list(bucket.list_blobs(prefix=folder_prefix))
        for blob in blobs:
            if blob.name.endswith(extension):
                return blob.name
        return None
    except Exception as e:
        print(f"⚠️ 雲端搜尋失敗: {e}")
        return None


def download_file_from_storage(cloud_path, local_path):
    """將雲端檔案抓回本地暫存目錄"""
    try:
        blob = bucket.blob(cloud_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        print(f"📥 正在從雲端下載: {cloud_path}")
        blob.download_to_filename(local_path)
        return local_path
    except Exception as e:
        print(f"❌ 下傳失敗: {e}")
        return None


def get_signed_url(cloud_path):
    """僅獲取簽署網址而不進行實體下載"""
    try:
        blob = bucket.blob(cloud_path)
        if not blob.exists():
            return None
        return blob.generate_signed_url(expiration=timedelta(days=36500))
    except Exception as e:
        print(f"⚠️ 網址簽署失敗: {e}")
        return None
