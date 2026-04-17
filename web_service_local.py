import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from config_local import db
from chat_Gemini_local import handle_chat_request

# ==========================================
# [標記：W01] Flask API 服務定義
# ==========================================

app = Flask(__name__)
CORS(app)  # 允許跨網域請求 (CORS)

@app.route("/")
def home():
    """首頁導向，用於確認服務存活"""
    return "🚀 WhisGe Local Backend is Alive and Running!"

@app.route("/chat", methods=["POST"])
def chat():
    """對話 API 端點：將請求轉發至 chat_Gemini_local 模組"""
    try:
        data = request.get_json()
        return handle_chat_request(db, data)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Web Service 發生錯誤: {str(e)}"}), 500

def run_server():
    """啟動 Flask 伺服器"""
    port = int(os.environ.get("PORT", 10000))
    print(f"📡 API 伺服器已在 PORT {port} 準備就緒")
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    # 獨立執行測試
    run_server()
