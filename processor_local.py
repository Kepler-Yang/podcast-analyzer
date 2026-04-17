import os
import re
import json
import time
import subprocess
import yt_dlp
import shutil
import torch
import whisper
from pydantic import BaseModel, Field
from typing import List
from google import genai
from config_local import GEMINI_MODEL

# ==========================================
# [標記：P01] 數據結構與 AI 指令 (Pydantic / Prompts)
# ==========================================

class Highlight(BaseModel):
    timeStart: str = Field(description="hh:mm:ss")
    timeEnd: str = Field(description="hh:mm:ss")
    desc: str = Field(description="議題重點說明")

class AnalysisResult(BaseModel):
    title: str = Field(description="影片標題")
    investment_insight: str = Field(description="核心投資洞察 (換行排列)")
    stocks: List[str] = Field(description="個股清單")
    sectors: List[str] = Field(description="產業清單")
    highlights: List[Highlight] = Field(description="完整議題時間序")

# **PROMPT鎖定**：除非 USER 提出，否則禁止修改此參數。
SYSTEM_PROMPT = """
# Role
你是一位具備頂尖科技財經分析師視野的「專業音訊分析助手」。
請分析SRT逐字稿內容，並嚴格根據提供的 Schema 輸出 JSON。
# Task
1. 全文覆蓋 (Mandatory)：請將 highlights 段落完整覆蓋整段時間序 (從 00:00:00 到結尾)。不可因為內容過長而只摘要前半段，必須持續產出直到逐字稿結束。
2. 段落密度：平均每 3~5 分鐘標註一個段落議題，確保時間軸具有連續性，不可以有超過 10 分鐘的空白遺漏。
3. 精準校對：修正 SRT 錯字與同音異字（如：道瓊, 費半,），常見人名清單：謝孟恭, 股癌, 游庭皓, 兆華與股惑仔, 李兆華, 阿格力, 廖婉婷, 林漢偉, 陳唯泰, 蔡明翰, 黃豐凱, 股魚, 艾綸, 林信富, 紀緯明, 陳威良, 謝富旭, 楊雲翔, 張捷, 楚狂人。
4. 雜訊過濾：忽略廣告與閒聊，專注於財經與產業資訊。
5. 提取投資洞察、個股與產業族群。
6. 語言：一律使用台灣繁體中文。
"""

# ==========================================
# [標記：P02] 文字與時間格式化工具
# ==========================================

def get_safe_filename(text):
    """移除路徑非法字元，確保存檔安全"""
    return re.sub(r'[\\/*?:"<>|]', "", text).strip()[:100]

def format_time(seconds):
    """秒數轉 SRT 標準格式"""
    ms = int((seconds - int(seconds)) * 1000)
    h = int(seconds // 3600); m = int((seconds % 3600) // 60); s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def preprocess_srt_to_seconds(srt_content):
    """
    【關鍵優化】將龐大的 SRT 壓縮為精簡格式給 AI 閱讀。
    保留時間點 [hh:mm:ss] 同時刪除宂餘資訊以節省 Token。
    """
    lines = srt_content.strip().split("\n")
    processed = []
    for line in lines:
        line = line.strip()
        if " --> " in line:
            start_time = line.split(" --> ")[0].split(",")[0].split(".")[0]
            processed.append(f"[{start_time}]")
        elif not line.isdigit() and line:
            if processed and processed[-1].startswith("["):
                processed[-1] = f"{processed[-1]} {line}"
            else: processed.append(line)
    return "\n".join(processed)

# ==========================================
# [標記：P03] 影音提取管線 (Pipeline)
# ==========================================

# 載入運算模型 (啟動時執行一次)
WHISPER_SIZE = "base"
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"📥 載入 Whisper ({WHISPER_SIZE}) 於 {device}...")
whisper_model = whisper.load_model(WHISPER_SIZE, device=device)

def process_audio_pipeline(url, task_id, db, temp_dir):
    """
    執行 下載 -> 轉錄 流程。
    本地版本特色：不受外部 API 檔案大小限制，優先利用 GPU。
    """
    os.makedirs(temp_dir, exist_ok=True)
    
    def update_task_status(msg, progress):
        db.collection("tasks").document(task_id).update({"status_msg": msg, "progress": progress})

    # [Step 1] 獲取資訊
    update_task_status("🔎 [1/5] 正在解析網址與預估長度... (約需 5-10 秒)", 15)
    with yt_dlp.YoutubeDL({}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "未知標題")
        safe_title = get_safe_filename(title)
        local_srt = os.path.join(temp_dir, f"{safe_title}.srt")
        
        # 🚀 [修復] 將抓取到的影片資訊更新至 Firestore，確展示預覽卡片 (S03)
        duration_sec = info.get("duration", 0)
        mins, secs = divmod(int(duration_sec), 60)
        hrs, mins = divmod(mins, 60)
        duration_text = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
        
        uploader = info.get("series") or info.get("uploader") or info.get("channel") or "未知頻道"
        
        db.collection("tasks").document(task_id).update({
            "metadata": {
                "title": title,
                "channel": uploader,
                "duration": duration_sec,
                "duration_text": duration_text,
                "thumbnail": info.get("thumbnail", ""),
            }
        })
    
    # 3. 提取音軌
    update_task_status("📥 [2/5] 正在提取音訊... (預計需 1~2 分鐘)", 30)
    final_audio = os.path.join(temp_dir, "audio.m4a")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": final_audio,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
        ydl.download([url])

    # 4. 本地 Whisper 轉錄
    update_task_status("🚀 [3/5] Whisper 正在高速轉錄逐字稿... (預計 3~5 分鐘)", 66)
    result = whisper_model.transcribe(
        final_audio, 
        language="zh", 
        initial_prompt="以下是繁體中文的逐字稿，包含台灣慣用語，請確保輸出為繁體中文。",
        fp16=True if device == "cuda" else False,
        verbose=False
    )
    
    srt_lines = []
    for i, seg in enumerate(result["segments"], 1):
        srt_lines.append(f"{i}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text'].strip()}\n")
    
    trans_srt = "\n".join(srt_lines)
    with open(local_srt, "w", encoding="utf-8") as f: f.write(trans_srt)
    
    return {"srt_path": local_srt, "srt_content": trans_srt}

# ==========================================
# [標記：P04] Gemini AI 分析引擎
# ==========================================

def run_gemini_analysis(srt_content, output_json_path, task_id, db):
    """呼叫 Gemini 進行深度財經摘要"""
    db.collection("tasks").document(task_id).update({"status_msg": "🧠 [4/5] Gemini 正在閱讀內容並撰寫深度分析... (預計 20-40 秒)", "progress": 80})
    
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    clean_text = preprocess_srt_to_seconds(srt_content)
    
    # 實作重試機制 (503/429 防禦)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"逐字稿內容：\n{clean_text}",
                config={
                    "system_instruction": SYSTEM_PROMPT.strip(),
                    "response_mime_type": "application/json",
                    "response_json_schema": AnalysisResult.model_json_schema()
                }
            )
            break
        except Exception as e:
            if attempt == 2: raise e
            time.sleep(3)

    data = AnalysisResult.model_validate_json(response.text).model_dump()
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data
