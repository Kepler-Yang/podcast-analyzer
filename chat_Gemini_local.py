import os
import time
import requests
import json
from flask import jsonify
from google.cloud.firestore import FieldFilter
from config_local import db, GEMINI_MODEL
from firebase_storage_local import url_to_storage_key
from processor_local import preprocess_srt_to_seconds

# ==========================================
# [標記：C01] 對話工作階段管理 (Session Memory)
# ==========================================

# 結構：{ "url_hash": {"chat": chat_session, "client": client} }
active_chat_sessions = {}

def handle_chat_request(db_instance, data):
    """
    處理來自前端的 Chat 請求。
    支援實體 Podcast 快取與「測試模式」攔截。
    """
    try:
        if not data: return jsonify({"status": "error", "message": "無數據"}), 400
        
        task_id = data.get("taskId")
        message = data.get("message")
        
        # 1. 測試模式 (TEST) 處理
        if task_id == "test_demo_task":
            url_hash = "test_demo_hash"
            srt_url = "https://kepler-yang.github.io/podcast-analyzer/preview.json" # 預設測試來源
        else:
            # 2. 正規流程：從 taskId 追蹤 SRT 網址
            task_doc = db_instance.collection("tasks").document(task_id).get()
            if not task_doc.exists:
                return jsonify({"status": "error", "message": "找不到任務"}), 404
                
            task_data = task_doc.to_dict()
            url_hash = url_to_storage_key(task_data.get("url"))
            transcript_id = task_data.get("transcriptId")
            
            if not transcript_id:
                return jsonify({"status": "error", "message": "尚未分析完成"}), 404
                
            # 從 transcripts 獲取下載連結 (精準定位)
            trans_doc = db_instance.collection("transcripts").document(transcript_id).get()
            if not trans_doc.exists:
                return jsonify({"status": "error", "message": "分析結果文檔遺失"}), 404
                
            srt_url = trans_doc.to_dict().get("srt_url")

        # 3. 如果是新對話，則初始化 Gemini Session [標記：C02]
        if url_hash not in active_chat_sessions:
            print(f"🧠 初始化對話 Session: {url_hash}")
            api_key = os.environ.get("GEMINI_API_KEY")
            from google import genai
            client = genai.Client(api_key=api_key)
            
            # 下載並壓縮 SRT 作為背景知識
            res = requests.get(srt_url, timeout=10)
            clean_srt = preprocess_srt_to_seconds(res.text)
            
            # 定義助手人設與背景
            sys_inst = (
                "你是一個專業的 Podcast 分析助手。以下是該集的內容供參考：\n\n"
                f"<transcript>\n{clean_srt}\n</transcript>\n\n"
                "請用台灣繁體中文回答，並校正逐字稿中的潛在錯字。"
                "SRT是使用whisper速聽轉錄，因此會有錯字，請你在回答前需要先校正錯字\n"
                "常見人名清單：謝孟恭, 股癌, 游庭皓, 兆華與股惑仔, 李兆華, 阿格力, 廖婉婷, 林漢偉, 陳唯泰, 蔡明翰, 黃豐凱, 股魚, 艾綸, 林信富, 紀緯明, 陳威良, 謝富旭, 楊雲翔, 張捷, 楚狂人。\n\n"
            )
            
            chat_session = client.chats.create(
                model=GEMINI_MODEL,
                config={"system_instruction": sys_inst, "temperature": 0.5}
            )
            active_chat_sessions[url_hash] = {"chat": chat_session, "client": client}

        # 4. 發送訊息與重試邏輯 [標記：C03]
        chat = active_chat_sessions[url_hash]["chat"]
        for attempt in range(2):
            try:
                response = chat.send_message(message)
                return jsonify({"status": "success", "reply": response.text})
            except Exception as e:
                if attempt == 1: raise e
                time.sleep(3)

    except Exception as e:
        print(f"❌ Chat Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
