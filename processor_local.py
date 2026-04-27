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
3. 精準校對與實體對齊：
   - 【關鍵】修正 SRT 錯字與同音異字。請優先參考下方提供的「標準個股清單」。
   - 若逐字稿出現音近但字錯的情況（如：台機電、連發科），必須依據清單修正為標準名稱（如：台積電、聯發科）。
   - 族群名稱（Sectors）也請優先對齊清單中的分類。
   - 常見人名清單：謝孟恭, 股癌, 游庭皓, 兆華與股惑仔, 李兆華, 阿格力, 廖婉婷, 林漢偉, 陳唯泰, 蔡明翰, 黃豐凱, 股魚, 艾綸, 林信富, 紀緯明, 陳威良, 謝富旭, 楊雲翔, 張捷, 楚狂人。
4. 雜訊過濾：忽略廣告與閒聊，專注於財經與產業資訊。
5. 提取投資洞察、個股與產業族群。
6. 語言：一律使用台灣繁體中文。
"""

SRT_CORRECTION_PROMPT = """
# Role
你是一位專業的逐字稿校對員，精通財經、半導體與 AI 產業術語。

# Task
請校對下方的 SRT 逐字稿，修正語音辨識產生的錯字、同音異字與標點符號。

# Rules
1. **嚴禁修改時間戳 (Timestamps)**：例如 `00:01:23,456 --> 00:01:25,000` 必須原封不動保留。
2. **實體對齊**：請優先參考提供的「標準清單」，將錯字修正為正確名稱。
3. **語氣精煉**：在不改變語意的前提下，修正贅字（如：那那個、然後然後）。
4. **輸出格式**：必須維持標準 SRT 格式輸出，不可遺漏任何段落。
5. **語言**：統一使用「繁體中文」。
"""

def load_stock_reference():
    """從根目錄 stocklist.json 載入個股與族群參考清單"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "stocklist.json")
    if not os.path.exists(path):
        return "", []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 格式化為 Gemini 易讀的字串
        ref_lines = ["\n### 標準個股與族群參考清單 (請務必以此校正同音異字)："]
        all_stocks = []
        for item in data:
            s_name = item.get("stock", "")
            s_id = item.get("stockID", "")
            sectors = ", ".join(item.get("sectors", []))
            ref_lines.append(f"- {s_name} ({s_id}): {sectors}")
            all_stocks.append(s_name)
            
        return "\n".join(ref_lines), all_stocks
    except Exception as e:
        print(f"⚠️ 載入 stocklist.json 失敗: {e}")
        return "", []

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
    ydl_opts = {
        "quiet": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
        "extract_flat": True, # 改為 True 以獲得更廣泛的列表支援
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.37 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.37",
        "referer": "https://www.google.com/",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        if not info:
            raise Exception("無法從該網址提取資訊。建議：請嘗試提供「單集節目」的網址 (帶有 ?i= 參數的連結)，解析成功率會更高。")

        # 如果是節目總頁面 (Playlist)，自動抓取最新的一集
        if "entries" in info:
            print("📅 偵測到節目總頁面，自動選取最新一集...")
            info = info["entries"][0]
            url = info.get("url") or url

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

    # 4. 本地 Whisper 轉錄 (優化引導詞)
    update_task_status("🚀 [3/5] Whisper 正在高速轉錄逐字稿... (預計 3~5 分鐘)", 66)
    
    # 動態獲取部分個股名稱作為 Whisper 引導
    _, stock_names = load_stock_reference()
    sample_stocks = "、".join(stock_names[:15]) if stock_names else "台積電、聯發科、鴻海"
    whisper_prompt = f"這是財經 Podcast 逐字稿，包含台股與美股術語，如：{sample_stocks}。請確保輸出為繁體中文。"

    result = whisper_model.transcribe(
        final_audio, 
        language="zh", 
        initial_prompt=whisper_prompt,
        fp16=True if device == "cuda" else False,
        verbose=False
    )
    
    srt_lines = []
    for i, seg in enumerate(result["segments"], 1):
        srt_lines.append(f"{i}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text'].strip()}\n")
    
    trans_srt = "\n".join(srt_lines)
    
    with open(local_srt, "w", encoding="utf-8") as f: 
        f.write(trans_srt)
    
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
    
    # 載入動態校正清單
    stock_ref_text, _ = load_stock_reference()
    final_prompt = f"逐字稿內容：\n{clean_text}\n\n{stock_ref_text}"
    
    # 實作重試機制 (503/429 防禦)
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=final_prompt,
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

def batch_correct_srt(srt_content, db, task_id):
    """將 SRT 分段並交由 Gemini 進行大規模校對"""
    db.collection("tasks").document(task_id).update({"status_msg": "✍️ [3.5/5] 正在進行 SRT 全文精準校對... (分段處理中)", "progress": 75})
    
    lines = srt_content.strip().split('\n')
    chunks = []
    current_chunk = []
    
    # 每 100 個 SRT 區塊分為一組 (大約 400-500 行)
    for i in range(0, len(lines), 400):
        chunks.append("\n".join(lines[i:i+400]))
        
    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    stock_ref_text, _ = load_stock_reference()
    
    corrected_chunks = []
    for idx, chunk in enumerate(chunks):
        print(f"📦 正在校對第 {idx+1}/{len(chunks)} 個區塊...")
        final_prompt = f"請校對以下 SRT 內容段落：\n\n{chunk}\n\n參考資料：\n{stock_ref_text}"
        
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=final_prompt,
                    config={"system_instruction": SRT_CORRECTION_PROMPT.strip()}
                )
                corrected_chunks.append(response.text.strip())
                break
            except:
                time.sleep(5)
                
    return "\n\n".join(corrected_chunks)
