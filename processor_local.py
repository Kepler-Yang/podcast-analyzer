import os
import re
import json
import time
import subprocess
import yt_dlp
import shutil
import tempfile
from pydantic import BaseModel, Field
from typing import List
import whisper
import torch
from google import genai
from dotenv import load_dotenv  # 🚀 [新增] 載入環境變數工具

# 🚀 [解決核心問題] 防止 OpenMP 重複初始化導致的崩潰
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# 啟動時自動從 .env 檔案讀取設定值
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(base_dir, ".env"))

# **GEMINI_MODEL 鎖定**：除非 USER 提出，否則禁止修改此參數。
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

# 載入原生 Whisper 模型 (與 run_whisper_v2.py 相同機制)
WHISPER_MODEL_SIZE = "base"
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"📥 正在載入 OpenAI Whisper 模型 ({WHISPER_MODEL_SIZE}) 於 {device} (將使用 {'GPU' if device == 'cuda' else 'CPU'})...")
whisper_model = whisper.load_model(WHISPER_MODEL_SIZE, device=device)
# **GEMINI_MODEL 鎖定**：除非 USER 提出，否則禁止修改此參數。
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"


# ==========================================
# [二、 資料結構定義 (Pydantic Models)]
# ==========================================
# **Json結構鎖定**：除非 USER 提出，否則禁止修改此參數。
class Highlight(BaseModel):
    timeStart: str = Field(description="hh:mm:ss")
    timeEnd: str = Field(description="hh:mm:ss")
    desc: str = Field(description="段落說明 (台灣繁體中文)")


class AnalysisResult(BaseModel):
    title: str = Field(description="影片標題 (台灣繁體中文)")
    investment_insight: str = Field(
        description="核心投資分析，請使用 1. 2. 3. 序號並換行排列，每點之間空兩行。"
    )
    stocks: List[str] = Field(description="本集提到的個股名單")
    sectors: List[str] = Field(description="本集提到的產業/技術族群名單")
    highlights: List[Highlight] = Field(
        description="全文議題拆解，必須完整覆蓋整段時間序，依討論議題切分段落，不可有超過10分鐘的空白遺漏"
    )


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


def format_time(seconds):
    """將秒數轉為 00:00:00,000 格式 (符合 SRT)"""
    milliseconds = int((seconds - int(seconds)) * 1000)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def get_safe_filename(text):
    """將文字轉換為合法檔名，移除特殊字元"""
    # 移除或取換非文字字元
    safe_text = re.sub(r'[\\/*?:"<>|]', "", text)
    # 取前 100 個字元避免檔名過長
    return safe_text.strip()[:100]


def preprocess_srt_to_seconds(srt_content):
    """
    將 SRT 壓縮為精簡格式，但在每一句話前保留精確的起始時間 [hh:mm:ss]。
    1. 移除毫秒、序號與空行。
    2. 保留每一句的精確秒數起點，不進行合併。
    3. 格式：[00:12:34] 文字內容
    """
    lines = srt_content.strip().split("\n")
    processed = []

    for line in lines:
        line = line.strip()
        if " --> " in line:
            # 格式解析：00:00:07,500 或是 00:00:07.500 (VTT)
            start_time_part = line.split(" --> ")[0]
            # 只取 hh:mm:ss 部分，忽略毫秒 (同時防禦逗號與點號)
            h_m_s = start_time_part.split(",")[0].split(".")[0]
            processed.append(f"[{h_m_s}]")
        elif line.isdigit() or not line:
            continue
        else:
            # 這是文字內容，接續在最後一個時間標記後面
            if processed and processed[-1].startswith("["):
                # 如果上一行是時間標記，則將文字併入該行
                processed[-1] = f"{processed[-1]} {line}"
            else:
                processed.append(line)

    return "\n".join(processed)


def process_audio_pipeline(url, task_id, db, temp_dir):
    """核心處理流程：下載音檔 + Whisper 轉錄 (不含 Gemini 分析)"""
    os.makedirs(temp_dir, exist_ok=True)

    # 先預給一個基本檔名，拿到 title 後會更新
    local_srt = os.path.join(temp_dir, "transcript.srt")

    def update_task_status(msg, progress):
        print(f"🗳️ [{progress}%] {msg}")
        db.collection("tasks").document(task_id).update(
            {"status_msg": msg, "progress": progress}
        )

    # 1️⃣ 本地環境 Cookie 偵測 (選配)
    cookie_path = "cookies.txt" if os.path.exists("cookies.txt") else None
    if not cookie_path and os.path.exists("youtube.com_cookies.txt"):
        cookie_path = "youtube.com_cookies.txt"

    # [Step 1] 獲取資訊
    update_task_status("🔎 [1/5] 正在解析網址與預估長度... (約需 5-10 秒)", 15)
    try:
        # 先以最輕量化方式獲取 metadata
        with yt_dlp.YoutubeDL({"quiet": True, "nocheckcertificate": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            duration_sec = info.get("duration", 0)
            title = info.get("title", "未知標題")
            # 🚀 [核心更新] 根據標題定義安全檔名
            safe_title = get_safe_filename(title)
            local_srt = os.path.join(temp_dir, f"{safe_title}.srt")
            local_json = os.path.join(temp_dir, f"{safe_title}.json")
            uploader = (
                info.get("series")
                or info.get("uploader")
                or info.get("channel")
                or info.get("creator")
                or "未知頻道"
            )

            # 計算易讀的時間格式 (例如 01:20:30 或 05:10)
            mins, secs = divmod(int(duration_sec), 60)
            hrs, mins = divmod(mins, 60)
            duration_text = (
                f"{hrs:02d}:{mins:02d}:{secs:02d}"
                if hrs > 0
                else f"{mins:02d}:{secs:02d}"
            )

            db.collection("tasks").document(task_id).update(
                {
                    "metadata": {
                        "title": title,
                        "channel": uploader,
                        "duration": duration_sec,
                        "duration_text": duration_text,  # 🚀 修正：補上前端需要的格式化文字
                        "thumbnail": info.get("thumbnail", ""),
                    }
                }
            )

        # ⚡ 1.2 執行「字幕優先攔截」 (僅限 YouTube)
        has_existing_subs = False
        if not ("apple.com" in url):
            update_task_status("📡 正在嘗試抓取 YouTube 既有字幕 (可節省 90% 處理時間)...", 20)
            try:
                # 擴充語言包容量，不再限制嚴格檔名
                with yt_dlp.YoutubeDL({
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": ["zh-Hant", "zh-TW", "zh-HK", "zh-Hans", "zh"],
                    "outtmpl": os.path.join(temp_dir, "yt_sub.%(ext)s"),
                    "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
                    "quiet": True,
                    "nocheckcertificate": True,
                }) as ydl_s:
                    ydl_s.download([url])
                
                # 放寬掃描：任何含有 yt_sub 的 .srt 或 .vtt 都收
                for f in os.listdir(temp_dir):
                    if (f.endswith(".srt") or f.endswith(".vtt")) and "yt_sub" in f:
                        # 找到直接重新命名為預期的 local_srt (若為 vtt 也強制被命名為 srt 給後端)
                        shutil.copy2(os.path.join(temp_dir, f), local_srt)
                        has_existing_subs = True
                        print(f"🎯 成功攔截既有字幕: {f}，跳過轉錄流程。")
                        break
            except Exception as sub_e:
                print(f"⚠️ 無法下載既有字幕，將改用本地 Whisper 轉錄: {sub_e}")

    except Exception as e:
        update_task_status(f"❌ 解析失敗: {str(e)}", -1)
        raise e

    # 📏 核心壓縮計算：目標設為 20MB (約 25MB 的 80%)，以抵銷封裝開銷與編碼誤差
    # 算式：(20 * 1024 KB * 8 bit) / 時長 = 每秒可分配的 bit rate
    target_bitrate_kbps = int((20 * 1024 * 8) / max(duration_sec, 1))
    safe_abr = min(128, max(16, target_bitrate_kbps))
    print(f"📉 根據時長 ({duration_sec}s) 調整目標位元率為: {safe_abr}kbps")

    # 🔍 [新增] 檢查本地是否已有先前下載的音檔 (斷點續跑)
    final_audio = None
    audio_extensions = [".m4a", ".opus", ".mp3", ".webm", ".ogg", ".mp4"]
    for f in os.listdir(temp_dir):
        if any(f.endswith(ext) for ext in audio_extensions) and f.startswith("audio"):
            final_audio = os.path.join(temp_dir, f)
            file_size_mb = os.path.getsize(final_audio) / (1024 * 1024)
            print(f"🎯 偵測到本地快取音檔: {f} ({file_size_mb:.2f} MB)，跳過下載步驟！")
            update_task_status(f"🎯 偵測到本地快取音檔 ({file_size_mb:.1f}MB)，跳過下載！", 50)
            break

    is_apple_podcast = "apple.com" in url

    # [策略 A] 長篇 Apple Podcast 優化：直接 ffmpeg 串流下載 (本地版不需壓縮)
    if not final_audio and is_apple_podcast and duration_sec > 900:
        mins = int(duration_sec // 60)
        update_task_status(
            f"🎙️ [2/5] 偵測到長篇 Podcast ({mins}分鐘)，串流下載中... (可能需要 1-3 分鐘，請稍候)",
            30,
        )
        audio_url = info.get("url")
        final_audio = os.path.join(temp_dir, "audio.mp3")

        # 本地版不受 25MB 限制，直接 copy 原始音軌，不轉碼
        ffmpeg_cmd = [
            "ffmpeg",
            "-i",
            audio_url,
            "-vn",
            "-acodec",
            "copy",   # 直接複製，不轉碼 (避免 libopus 不存在的問題)
            "-y",
            final_audio,
        ]
        subprocess.run(ffmpeg_cmd, check=True)

    # [策略 B] Youtube 與其他平台：原生 yt-dlp 強制下載
    if not final_audio and not has_existing_subs:
        mins = int(duration_sec // 60)
        update_task_status(f"📥 [2/5] 正在提取音訊 ({mins}分鐘)... (預計需 1~2 分鐘)", 30)
        
        # 模仿 test_processor.py 確保優先獲取 m4a 並節省空間
        format_spec = f"bestaudio[abr<={safe_abr}][ext=m4a]/bestaudio[abr<={safe_abr}]/worstaudio"

        ydl_opts = {
            "format": format_spec,
            "outtmpl": os.path.join(temp_dir, "audio_raw.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "cookiefile": cookie_path if (cookie_path and os.path.exists(cookie_path)) else None
        }

        try:
            print(f"🚀 啟動原生下載模式...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                download_info = ydl.extract_info(url, download=True)
                raw_file = ydl.prepare_filename(download_info)
        except Exception as e:
            error_msg = str(e).lower()
            if "cookie" in error_msg or "sign in" in error_msg or "bot" in error_msg:
                print("⚠️ 需要身分驗證，嘗試掛載手機 UA 進行重試...")
                ydl_opts["user_agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    download_info = ydl.extract_info(url, download=True)
                    raw_file = ydl.prepare_filename(download_info)
            else:
                raise e

        # 由於本地端 Whisper 不受外部 API 的檔案大小限制，我們直接跳過任何轉碼壓縮手續！
        file_size_mb = os.path.getsize(raw_file) / (1024 * 1024)
        print(f"⚖️ 音軌下載完成，大小：{file_size_mb:.2f} MB")
        
        print("⚡ 本地端不限檔案大小，原始檔案直接交付轉錄。")
        final_audio = raw_file

    # [Step 3] 取得逐字稿內容 (從本地轉錄或既有字幕)
    if has_existing_subs:
        update_task_status("✅ 已成功提取既有字幕，跳過轉錄階段 (節省 100% 算力)！", 70)
        with open(local_srt, "r", encoding="utf-8") as f:
            trans_srt = f.read()
    else:
        update_task_status("🚀 [3/5] 本地 Whisper 正在轉錄逐字稿... (運算時間視電腦效能而定)", 66)
        
        # 依照 run_whisper_v2.py 呼叫原生 transcribe
        result = whisper_model.transcribe(
            final_audio, 
            language="zh",
            initial_prompt="以下是繁體中文的逐字稿，包含台灣慣用語，請確保輸出為繁體中文。",
            fp16=True if device == "cuda" else False,
            verbose=False
        )

        srt_lines = []
        for i, seg in enumerate(result["segments"], start=1):
            srt_lines.append(
                f"{i}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text'].strip()}\n"
            )
        
        trans_srt = "\n".join(srt_lines)
        with open(local_srt, "w", encoding="utf-8") as f:
            f.write(trans_srt)

    # ✅ Pipeline 結束：回傳 SRT 結果，Gemini 分析由 main_local.py 控制
    return {
        "srt_path": local_srt,
        "audio_path": final_audio,
        "srt_content": trans_srt,
    }


def run_gemini_analysis(srt_content, output_json_path, task_id=None, db=None):
    """
    獨立的 Gemini AI 分析函式。
    可由完整 pipeline 呼叫，也可由 main_local.py 在有 SRT 快取時直接呼叫。
    :param srt_content: SRT 逐字稿的純文字內容
    :param output_json_path: JSON 分析結果的本地存檔路徑
    :param task_id: Firebase 任務 ID (用於更新進度，可選)
    :param db: Firestore client (用於更新進度，可選)
    :return: 分析結果 dict
    """
    def update_status(msg, progress):
        print(f"🗳️ [{progress}%] {msg}")
        if db and task_id:
            db.collection("tasks").document(task_id).update(
                {"status_msg": msg, "progress": progress}
            )

    update_status("🧠 [4/5] Gemini 正在閱讀內容並撰寫深度分析... (預計 20-40 秒)", 80)

    # 🚨 資安防護：強制從 .env 讀取，嚴禁將 API Key 寫死在程式碼中！
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("❌ 偵測不到 GEMINI_API_KEY，請確認 .env 檔案已設定正確。")

    local_gemini_client = genai.Client(api_key=api_key)

    clean_content = preprocess_srt_to_seconds(srt_content)
    response = local_gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"待處理逐字稿：\n{clean_content}\n\n請根據以上內容提供深度分析。\n\n【⚠️ 強制規定】: 你的所有回覆、標題與分析內容，必須使用嚴謹的「台灣繁體中文 (zh-TW)」輸出，絕對嚴禁出現任何簡體字與大陸用語。",
        config={
            "system_instruction": SYSTEM_PROMPT.strip(),
            "response_mime_type": "application/json",
            "response_json_schema": AnalysisResult.model_json_schema(),
            "temperature": 1.0,
        },
    )

    # [Step 5] 解析與存檔
    update_status("📊 [5/5] 正在整理最後結果並存入雲端... (即將完成)", 95)
    try:
        structured_data = AnalysisResult.model_validate_json(response.text)
        json_data = structured_data.model_dump()
    except:
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        json_data = json.loads(match.group(0) if match else response.text.strip())

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    return json_data
