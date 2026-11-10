# Salita AI (TranscribePH) - Tagalog, English & Taglish AI Transcriber

An offline-first, high-accuracy video and audio transcription web application tailored specifically for **Tagalog, English, and Taglish (code-switching)** speech.

---

## 🚀 Key Features

- **Taglish & Colloquial Conditioning:** Uses Faster-Whisper with custom Filipino prompt conditioning (`kumusta`, `diba`, `sige`, `talaga`, `opo`, `actually`, `ano ba naman`, etc.) to accurately capture conversational code-switching without hallucinations.
- **✨ Linguistic Word Polisher:** Automatically cleans stutters (`pa-para` -> `para`, `yung... ang`), fixes false-starts, normalizes contractions (`a'y` -> `ay`, `par sa` -> `para sa`), and restores proper sentence capitalization and punctuation.
- **✨ 1-Click "Polish Words" Button:** Polish or proofread the entire transcript at any time from the web toolbar.
- **Synchronized Video Player:** Watch your video with real-time subtitle overlays. Click any timestamp in the transcript to jump playback directly to that segment.
- **Editable Transcript:** Fix or edit any misheard words or acronyms directly in the UI before exporting.
- **Flexible Exporting:** Export directly into:
  - **`.SRT`** (SubRip Subtitle file with millisecond accuracy)
  - **`.VTT`** (WebVTT for web players and video editors)
  - **`.TXT`** (Plain text transcript with timestamps)
  - **`.JSON`** (Structured data with start/end seconds)
- **100% Free, Local & Private:** Processes all videos locally on your computer using optimized INT8 Faster-Whisper and embedded FFmpeg. No API keys required.

---

## ⚡ How to Run

### Method 1: Double-Click Launcher (Windows)
Double-click `start_transcriber.bat`. It will automatically launch the server and open your browser to `http://127.0.0.1:8000`.

### Method 2: Command Line
```powershell
# Install dependencies
pip install -r requirements.txt

# Run server
python server.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## ⚙️ Model Selection Guide

| Model | Speed | Accuracy | Best For |
|---|---|---|---|
| **Base** | ⚡ Very Fast | Good | Casual videos, clear audio, general Taglish conversations |
| **Small** | 🚀 Balanced | High | Best balance of speed & colloquial slang accuracy |
| **Medium** | 🎯 In-depth | Very High | Maximum Taglish nuance, soft voices, or heavy background noise |
| **Tiny** | ⚡⚡ Instant | Fair | Fast drafts or long lecture recordings |
