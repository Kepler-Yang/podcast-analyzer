import os
import time
import requests
from flask import jsonify
from google.cloud.firestore import FieldFilter
from firebase_storage_local import url_to_storage_key
from processor_local import preprocess_srt_to_seconds, GEMINI_MODEL

# 用來暫存使用者的對話 Session，結構為 { "url_hash": {"chat": chat_session, "client": client} }
active_chat_sessions = {}

def handle_chat_request(db, data):
    """處理與 Gemini 的對話請求 (從 main_local.py 分離)"""
    try:
        if not data:
            return jsonify({"status": "error", "message": "無效的請求數據"}), 400

        task_id = data.get("taskId")
        message = data.get("message")

        if not task_id or not message:
            return jsonify({"status": "error", "message": "缺少 taskId 或 message"}), 400

        # 針對「測試模式 (TEST)」進行攔截
        if task_id == "test_demo_task":
            url_hash = "test_demo_hash"
            
            # 從「本地」或「網路」讀取 TEST.json 獲取 srt_url (單一真理來源)
            import json
            test_data = None
            test_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TEST.json")
            
            if os.path.exists(test_json_path):
                with open(test_json_path, "r", encoding="utf-8") as f:
                    test_data = json.load(f)
            else:
                # 🌐 若本地找不到，改從您的 GitHub Pages 抓取 (通吃方案)
                print("   🌐 本地找不到 TEST.json，嘗試從 GitHub Pages 抓取...")
                test_url = "https://kepler-yang.github.io/podcast-analyzer/TEST.json"
                try:
                    res_j = requests.get(test_url, timeout=10)
                    if res_j.status_code == 200:
                        test_data = res_j.json()
                except: pass

            if not test_data:
                return jsonify({"status": "error", "message": "找不到測試檔案 TEST.json (本地與網路皆失敗)"}), 404
                
            srt_url = test_data.get("srt_url")
            if not srt_url or srt_url == "#":
                return jsonify({"status": "error", "message": "測試檔案中沒有有效的 srt_url"}), 404
        else:
            # 正規流程：將 taskId 轉換為 url_hash
            task_doc = db.collection("tasks").document(task_id).get()
            if not task_doc.exists:
                return jsonify({"status": "error", "message": "找不到對應的任務"}), 404
                
            task_data = task_doc.to_dict()
            url = task_data.get("url")
            url_hash = url_to_storage_key(url)

            # 正規流程：準備系統上下文：直接從 transcripts 集合中抓取下載用的 srt_url
            transcript_docs = db.collection("transcripts").where(filter=FieldFilter("taskId", "==", task_id)).limit(1).get()
            
            if not transcript_docs:
                return jsonify({"status": "error", "message": "找不到該 Podcast 的分析紀錄"}), 404
                
            transcript_data = transcript_docs[0].to_dict()
            srt_url = transcript_data.get("srt_url")
            
            if not srt_url or srt_url == "#":
                return jsonify({"status": "error", "message": "該 Podcast 沒有產生逐字稿"}), 404

                
        # 🚨 檢查是否已有 Session，若無則建立
        if url_hash not in active_chat_sessions:
            print(f"🧠 [Chat] 初始化 {url_hash} 的 AI 對話大腦...")
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
                api_key = os.environ.get("GEMINI_API_KEY")

            from google import genai
            client = genai.Client(api_key=api_key)

            srt_content = ""
            print("   ☁️ 從雲端網址下載 SRT 作為對話上下文...")
            try:
                res = requests.get(srt_url, timeout=15)
                if res.status_code == 200:
                    srt_content = res.text
                    print("   ✅ 成功下載 SRT Context")
                else:
                    return jsonify({"status": "error", "message": f"下載逐字稿失敗 (HTTP {res.status_code})"}), 500
            except Exception as req_e:
                return jsonify({"status": "error", "message": f"下載例外: {str(req_e)}"}), 500

            # 整理 SRT
            clean_content = preprocess_srt_to_seconds(srt_content)
            
            # 使用系統指令鎖定角色
            system_instruction = (
                "你是一個專業的 Podcast 分析助手。以下是你需要了解的該集 Podcast 完整逐字稿。\n\n"
                f"<podcast_transcript>\n{clean_content}\n</podcast_transcript>\n\n"
                "請根據這份逐字稿詳盡且專業地回答使用者的問題。你的回答必須完全使用「台灣繁體中文 (zh-TW)」。\n\n"
                "SRT逐字稿名詞修正：SRT是使用whisper速聽轉錄，因此會有錯字，請你在回答前需要先校正錯字\n"
                "常見人名清單：謝孟恭, 股癌, 游庭皓, 兆華與股惑仔, 李兆華, 阿格力, 廖婉婷, 林漢偉, 陳唯泰, 蔡明翰, 黃豐凱, 股魚, 艾綸, 林信富, 紀緯明, 陳威良, 謝富旭, 楊雲翔, 張捷, 楚狂人。\n\n"
            )

            # 建立並儲存 Session
            chat_session = client.chats.create(
                model=GEMINI_MODEL,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.5,
                }
            )
            active_chat_sessions[url_hash] = {
                "chat": chat_session,
                "client": client
            }

        # 🗨️ 開始對話 (加入 503 自動重試)
        print(f"💬 [Chat User]: {message}")
        chat = active_chat_sessions[url_hash]["chat"]
        
        response = None
        for attempt in range(3):
            try:
                response = chat.send_message(message)
                break
            except Exception as e:
                err_str = str(e)
                if ("503" in err_str or "429" in err_str) and attempt < 2:
                    wait_time = 3 # 使用者要求縮短為 3s
                    print(f"⚠️ [Chat] 伺服器繁忙 (503)，將於 {wait_time} 秒後重試 ({attempt+1}/2)...")
                    time.sleep(wait_time)
                    continue
                raise e

        print(f"🤖 [Chat AI]: {response.text[:50]}...")

        return jsonify({
            "status": "success",
            "reply": response.text
        })

    except Exception as e:
        print(f"❌ [Chat Error]: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
