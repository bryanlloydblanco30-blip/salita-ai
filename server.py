import os
import sys
import uuid
import json
import time
import shutil
import re
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

import av
# Compatibility patch for PyAV 19+ with faster-whisper
_orig_av_open = av.open
def _safe_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)
av.open = _safe_av_open

import imageio_ffmpeg
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import faster_whisper.audio
faster_whisper.audio.av.open = _safe_av_open
from faster_whisper import WhisperModel

app = FastAPI(title="TranscribePH Pro - Tagalog, English & Taglish AI Transcriber")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
PROCESSED_DIR = BASE_DIR / "processed"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# In-memory job state store
jobs: Dict[str, Dict[str, Any]] = {}

# Cached models to avoid reloading
loaded_models: Dict[str, WhisperModel] = {}

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

TAGLISH_HOTWORDS = (
    "kumusta sige talaga naman diba kasi opo oo hindi actually honestly literally "
    "grabe naman wait lang sandali tara salamat po ano ba naririnig napapansin"
)

def get_model(model_size: str = "medium", compute_type: str = "int8") -> WhisperModel:
    key = f"{model_size}_{compute_type}"
    if key not in loaded_models:
        print(f"[*] Loading Faster-Whisper model '{model_size}' with compute_type='{compute_type}'...")
        loaded_models[key] = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=max(2, os.cpu_count() or 4)
        )
    return loaded_models[key]

def extract_audio_from_video(video_path: Path, output_audio_path: Path) -> bool:
    """
    Extract 16kHz mono WAV using imageio-ffmpeg with dynamic audio normalization
    to boost quiet speech and balance levels.
    """
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-af", "dynaudnorm",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_audio_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError:
        fallback_cmd = [
            FFMPEG_EXE,
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_audio_path)
        ]
        try:
            subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return True
        except Exception as ex:
            print(f"[!] Audio extraction failed: {ex}")
            return False

def clean_repetitions(text: str) -> str:
    """Removes degenerate word/phrase repetition loops."""
    if not text:
        return ""
    
    # Deduplicate single words repeated consecutively 3+ times
    cleaned = re.sub(r'\b([A-Za-zÀ-ÿ]+)(?:[,\s]+)\1(?:[,\s]+\1){2,}\b', r'\1', text, flags=re.IGNORECASE)
    
    # Deduplicate 2-word phrases repeated consecutively 3+ times
    cleaned = re.sub(r'\b([A-Za-zÀ-ÿ]+\s+[A-Za-zÀ-ÿ]+)(?:[,\s]+)\1(?:[,\s]+\1){2,}\b', r'\1', cleaned, flags=re.IGNORECASE)

    # Clean duplicate punctuation
    cleaned = re.sub(r'([,.!?])\s*\1+', r'\1', cleaned)
    
    # Condense monolithic repeated word
    words = [w.strip(" ,.!?").lower() for w in cleaned.split() if w.strip(" ,.!?")]
    if len(words) >= 4 and len(set(words)) == 1:
        return words[0]

    return cleaned.strip()

def polish_text(text: str) -> str:
    """
    Linguistic polishing engine for Tagalog, English, and Taglish speech.
    Fixes:
    - Stutters & hesitation markers (e.g. 'yung... ang', 'pa-para')
    - Common Whisper phonetic slips in Philippine grammar
    - Spacing, capitalization, and punctuation
    """
    if not text:
        return ""
    
    t = text.strip()
    
    # 1. Clean stutter repetitions and false-starts
    t = re.sub(r'\b(\w+)\s*\.{2,}\s*\1\b', r'\1', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(yung|ang|na|sa|ay|mga)\s*\.{2,}\s*(yung|ang|na|sa|ay|mga)\b', r'\2', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(\w{1,3})-\1(\w+)\b', r'\1\2', t, flags=re.IGNORECASE)  # pa-para -> para

    # 2. Correct common Tagalog phonetic mistranscriptions from Whisper
    replacements = [
        (r'\ba\'y\b', 'ay'),
        (r'\bmarami(?:ng)?\s*(?:si\s*)?(?:[a-zA-Z]*alamad|alamat|lamat)\b', 'maraming salamat'),
        (r'\b(?:par|sebar|sparsai)\s*sa\b', 'para sa'),
        (r'\b(?:salarot|salarut)\b', 'sa laro'),
        (r'\b(?:naka-?dulit|nakadulit|nakakadulit)\s+ng\s+(?:nasama|masamandun|masama)\b', 'nagdudulot ng masama'),
        (r'\b(?:palitig|paligig)\b', 'paligid'),
        (r'\b(?:amas|ang\s*mas)\s*sa\s*sabi\b', 'ang masasabi'),
        (r'\bokey\b', 'okay'),
        (r'\bdi\s+ba\b', 'diba'),
        (r'\bn\'ung\b', 'noong'),
        (r'\bano\s*ba\s*\'?yan\b', 'ano ba \'yan'),
        (r'\bpala\'y\b', 'pala ay'),
        (r'\bdito\'y\b', 'dito ay'),
        (r'\bdoon\s*a\'y\b', 'doon ay'),
        (r'\bsa\'kin\b', 'sa akin'),
        (r'\bsa\'yo\b', 'sa iyo'),
        (r'\bn\'yo\b', 'ninyo'),
    ]
    for pat, rep in replacements:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    # 3. Clean up spacing and punctuation
    t = re.sub(r'\s+([,.?!])', r'\1', t)
    t = re.sub(r'([,.?!])(?=[^\s,.?!])', r'\1 ', t)
    t = re.sub(r'([.?!])\s*([.?!])+', r'\1', t)
    t = re.sub(r'\s+', ' ', t).strip()

    # 4. Sentence capitalization
    sentences = re.split(r'([.?!]\s+)', t)
    fixed = []
    for s in sentences:
        if s and not re.match(r'^[.?!]\s+$', s):
            fixed.append(s[0].upper() + s[1:] if len(s) > 1 else s.upper())
        else:
            fixed.append(s)
    t = ''.join(fixed)

    return t

def format_timestamp_srt(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"

def format_timestamp_vtt(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    msecs = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{msecs:03d}"

def generate_srt(segments: list) -> str:
    lines = []
    for idx, seg in enumerate(segments, 1):
        start = format_timestamp_srt(seg["start"])
        end = format_timestamp_srt(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)

def generate_vtt(segments: list) -> str:
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = format_timestamp_vtt(seg["start"])
        end = format_timestamp_vtt(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{start} --> {end}\n{text}\n")
    return "\n".join(lines)

def generate_txt(segments: list) -> str:
    return "\n".join(f"[{format_timestamp_srt(s['start'])} --> {format_timestamp_srt(s['end'])}] {s['text'].strip()}" for s in segments)

def transcribe_with_gemini(audio_path: Path, api_key: str, custom_prompt: str) -> list:
    """Transcribe audio using Google Gemini 2.5 Flash for 100% human-grade Taglish accuracy."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    print(f"[*] Uploading audio file ({audio_path.stat().st_size / 1024 / 1024:.2f} MB) to Google Gemini...")
    audio_file = client.files.upload(file=str(audio_path))

    system_instruction = (
        "You are an expert multilingual audio transcriber specialized in Tagalog (Filipino), English, and Taglish code-switching. "
        "Your task is to transcribe this audio file with 100% verbatim accuracy. "
        "Pay special attention to conversational Filipino grammatical particles (e.g., 'ba', 'naman', 'pala', 'talaga', 'kasi', 'po', 'opo', 'sige', 'diba', 'maraming salamat'). "
        "Return the output STRICTLY as a JSON array of segment objects. Each object must have:\n"
        "- 'start': float (start time in seconds)\n"
        "- 'end': float (end time in seconds)\n"
        "- 'text': string (the transcribed text for that segment)"
    )

    user_prompt = "Transcribe the audio completely into timestamped segments."
    if custom_prompt and custom_prompt.strip():
        user_prompt += f" Additional context/keywords: {custom_prompt.strip()}"

    print("[*] Requesting transcription from gemini-2.5-flash...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_file, user_prompt],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json"
        )
    )

    raw_json = response.text.strip()
    data = json.loads(raw_json)
    
    parsed = []
    for idx, item in enumerate(data, 1):
        start_sec = float(item.get("start", 0.0))
        end_sec = float(item.get("end", start_sec + 2.0))
        text = polish_text(str(item.get("text", "")).strip())
        if text:
            parsed.append({
                "id": idx,
                "start": round(start_sec, 2),
                "end": round(end_sec, 2),
                "start_fmt": format_timestamp_srt(start_sec),
                "end_fmt": format_timestamp_srt(end_sec),
                "text": text
            })
            
    # Cleanup remote file
    try:
        client.files.delete(name=audio_file.name)
    except Exception:
        pass

    return parsed

def run_transcription_worker(job_id: str, file_path: Path, engine: str, model_size: str, language_opt: str, custom_prompt: str, api_key: str):
    job = jobs[job_id]
    audio_path = PROCESSED_DIR / f"{job_id}.wav"
    try:
        job["status"] = "extracting_audio"
        job["progress"] = 15
        job["message"] = "Extracting audio and applying dynamic volume normalization..."
        
        if not extract_audio_from_video(file_path, audio_path):
            raise Exception("Failed to extract audio from video track.")
        
        parsed_segments = []

        if engine == "gemini":
            if not api_key or not api_key.strip():
                raise Exception("Gemini Engine selected, but no API key was provided.")
            
            job["status"] = "transcribing"
            job["progress"] = 40
            job["message"] = "Uploading audio to Google Gemini 2.5 Flash for high-precision Taglish transcription..."
            
            parsed_segments = transcribe_with_gemini(audio_path, api_key.strip(), custom_prompt)
            job["detected_language"] = "tl / en (Taglish)"
            job["language_probability"] = 1.0

        else:
            job["status"] = "loading_model"
            job["progress"] = 30
            job["message"] = f"Loading Faster-Whisper ({model_size}) model into memory..."
            
            model = get_model(model_size=model_size)
            
            job["status"] = "transcribing"
            job["progress"] = 45
            job["message"] = f"Transcribing with {model_size} neural network (Anti-repetition & Polishing active)..."
            
            lang = None if language_opt in ("auto", "", None) else language_opt
            
            hotwords = TAGLISH_HOTWORDS
            if custom_prompt and custom_prompt.strip():
                hotwords = f"{hotwords} {custom_prompt.strip()}"

            segments_gen, info = model.transcribe(
                str(audio_path),
                language=lang,
                hotwords=hotwords,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=600,
                    speech_pad_ms=300
                ),
                beam_size=5,
                best_of=5,
                temperature=[0.0, 0.2, 0.4, 0.6],
                condition_on_previous_text=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                compression_ratio_threshold=2.4,
                no_speech_threshold=0.6,
                hallucination_silence_threshold=2.0,
                language_detection_segments=4,
                word_timestamps=False
            )
            
            job["detected_language"] = info.language
            job["language_probability"] = round(info.language_probability, 3)
            job["duration"] = round(info.duration, 2)
            total_duration = max(info.duration, 1.0)
            
            for seg in segments_gen:
                clean_txt = clean_repetitions(seg.text.strip())
                polished = polish_text(clean_txt)
                
                if polished and len(polished) > 1:
                    seg_item = {
                        "id": len(parsed_segments) + 1,
                        "start": round(seg.start, 2),
                        "end": round(seg.end, 2),
                        "start_fmt": format_timestamp_srt(seg.start),
                        "end_fmt": format_timestamp_srt(seg.end),
                        "text": polished
                    }
                    parsed_segments.append(seg_item)
                    
                    prog = 45 + int((seg.end / total_duration) * 50)
                    job["progress"] = min(prog, 96)
                    job["message"] = f"Transcribing & Polishing... ({round(seg.end, 1)}s / {round(total_duration, 1)}s processed)"
                    job["live_segment_count"] = len(parsed_segments)

        job["segments"] = parsed_segments
        job["full_text"] = " ".join(s["text"] for s in parsed_segments)
        job["srt"] = generate_srt(parsed_segments)
        job["vtt"] = generate_vtt(parsed_segments)
        job["txt"] = generate_txt(parsed_segments)
        
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = f"Transcription complete! Generated {len(parsed_segments)} polished segments."
        print(f"[+] Job {job_id} completed with {len(parsed_segments)} polished segments.")
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        job["status"] = "failed"
        job["error"] = str(e)
        job["message"] = f"Transcription error: {str(e)}"
    finally:
        if audio_path.exists():
            try:
                os.remove(audio_path)
            except Exception:
                pass

@app.post("/api/transcribe")
async def start_transcription(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    engine: str = Form("whisper"),
    model_size: str = Form("medium"),
    language: str = Form("tl"),
    custom_prompt: Optional[str] = Form(""),
    api_key: Optional[str] = Form("")
):
    job_id = str(uuid.uuid4())
    ext = Path(file.filename or "video.mp4").suffix or ".mp4"
    saved_filename = f"{job_id}{ext}"
    saved_path = UPLOAD_DIR / saved_filename
    
    with open(saved_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    jobs[job_id] = {
        "id": job_id,
        "original_filename": file.filename,
        "video_url": f"/api/video/{saved_filename}",
        "status": "queued",
        "progress": 0,
        "message": "File uploaded. Starting transcription pipeline...",
        "created_at": time.time(),
        "engine": engine,
        "model_size": model_size,
        "segments": [],
        "full_text": "",
        "detected_language": None
    }
    
    background_tasks.add_task(
        run_transcription_worker,
        job_id,
        saved_path,
        engine,
        model_size,
        language,
        custom_prompt or "",
        api_key or os.getenv("GEMINI_API_KEY", "")
    )
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.put("/api/job/{job_id}/segments")
async def update_job_segments(job_id: str, payload: dict):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    new_segments = payload.get("segments", [])
    jobs[job_id]["segments"] = new_segments
    jobs[job_id]["full_text"] = " ".join(s["text"] for s in new_segments)
    jobs[job_id]["srt"] = generate_srt(new_segments)
    jobs[job_id]["vtt"] = generate_vtt(new_segments)
    jobs[job_id]["txt"] = generate_txt(new_segments)
    return {"status": "updated", "count": len(new_segments)}

@app.post("/api/job/{job_id}/polish")
async def polish_job_transcript(job_id: str, payload: dict = None):
    """
    Polishes words in all segments:
    - Fixes false-starts, stutter ellipses, and mistranscribed Tagalog particles
    - If api_key is provided, uses Gemini to perform AI-level linguistic enhancement.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    segments = job.get("segments", [])
    if not segments:
        return {"status": "empty", "segments": []}
    
    api_key = payload.get("api_key") if payload else None
    
    # Check if AI polish with Gemini is requested
    if api_key and api_key.strip():
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key.strip())
            
            prompt = (
                "You are an expert editor for Filipino, English, and Taglish video subtitles. "
                "Proofread and polish each of the following subtitle segment texts. "
                "Fix mistranscribed words, colloquial grammar slips, stuttering, and punctuation, "
                "while strictly preserving the exact natural tone, meaning, and code-switching. "
                "Return STRICTLY a JSON array of strings corresponding 1-to-1 to each input text.\n\n"
                f"Input Texts: {json.dumps([s['text'] for s in segments], ensure_ascii=False)}"
            )
            
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            polished_texts = json.loads(resp.text.strip())
            if isinstance(polished_texts, list) and len(polished_texts) == len(segments):
                for seg, p_txt in zip(segments, polished_texts):
                    seg["text"] = p_txt.strip()
        except Exception as e:
            print(f"[!] AI polish fallback to local rules: {e}")
            for seg in segments:
                seg["text"] = polish_text(seg["text"])
    else:
        # High-speed local linguistic polishing
        for seg in segments:
            seg["text"] = polish_text(seg["text"])

    job["segments"] = segments
    job["full_text"] = " ".join(s["text"] for s in segments)
    job["srt"] = generate_srt(segments)
    job["vtt"] = generate_vtt(segments)
    job["txt"] = generate_txt(segments)
    return {"status": "polished", "segments": segments, "count": len(segments)}

@app.get("/api/job/{job_id}/export/{format_type}")
async def export_transcript(job_id: str, format_type: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")
    
    orig_name = Path(job["original_filename"]).stem
    
    if format_type == "srt":
        content = job.get("srt", "")
        return PlainTextResponse(
            content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{orig_name}.srt"'}
        )
    elif format_type == "vtt":
        content = job.get("vtt", "")
        return PlainTextResponse(
            content,
            media_type="text/vtt; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{orig_name}.vtt"'}
        )
    elif format_type == "txt":
        content = job.get("txt", "")
        return PlainTextResponse(
            content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{orig_name}.txt"'}
        )
    elif format_type == "json":
        return JSONResponse(
            job.get("segments", []),
            headers={"Content-Disposition": f'attachment; filename="{orig_name}.json"'}
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Use srt, vtt, txt, or json.")

@app.get("/api/video/{filename}")
async def stream_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(file_path)

# Serve front-end
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Transcriber Frontend Initializing...</h1>")

if __name__ == "__main__":
    import uvicorn
    print("\n==========================================================")
    print("  TranscribePH Pro - Tagalog, English & Taglish AI Transcriber")
    print("  Access web UI at: http://127.0.0.1:8000")
    print("==========================================================\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
