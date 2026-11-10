// TranscribePH Application Logic
document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("transcribeForm");
  const fileInput = document.getElementById("videoFileInput");
  const dropZone = document.getElementById("dropZone");
  const selectedFilePill = document.getElementById("selectedFilePill");
  const selectedFileName = document.getElementById("selectedFileName");
  const selectedFileSize = document.getElementById("selectedFileSize");
  const clearFileBtn = document.getElementById("clearFileBtn");
  const startBtn = document.getElementById("startTranscribeBtn");

  const progressCard = document.getElementById("progressCard");
  const progressPhase = document.getElementById("progressPhase");
  const progressDetails = document.getElementById("progressDetails");
  const progressPercent = document.getElementById("progressPercent");
  const progressBarFill = document.getElementById("progressBarFill");
  const step1 = document.getElementById("step1");
  const step2 = document.getElementById("step2");
  const step3 = document.getElementById("step3");
  const step4 = document.getElementById("step4");

  const resultsWorkspace = document.getElementById("resultsWorkspace");
  const videoPlayer = document.getElementById("videoPlayer");
  const activeSubOverlay = document.getElementById("activeSubOverlay");
  const segmentsList = document.getElementById("segmentsList");
  const searchInput = document.getElementById("transcriptSearchInput");
  const copyAllBtn = document.getElementById("copyAllBtn");
  const polishWordsBtn = document.getElementById("polishWordsBtn");
  const saveEditsBtn = document.getElementById("saveEditsBtn");

  const exportMenuBtn = document.getElementById("exportMenuBtn");
  const exportMenu = document.getElementById("exportMenu");

  const metaFilename = document.getElementById("metaFilename");
  const metaLang = document.getElementById("metaLang");
  const metaDuration = document.getElementById("metaDuration");
  const metaSegmentsCount = document.getElementById("metaSegmentsCount");

  const jumpBackBtn = document.getElementById("jumpBackBtn");
  const togglePlayBtn = document.getElementById("togglePlayBtn");
  const jumpForwardBtn = document.getElementById("jumpForwardBtn");
  const playbackSpeed = document.getElementById("playbackSpeed");

  let currentJobId = null;
  let currentSegments = [];
  let pollInterval = null;

  // File Drag & Drop Handlers
  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("dragover");
    });
  });

  dropZone.addEventListener("drop", (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      fileInput.files = files;
      displaySelectedFile(files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      displaySelectedFile(fileInput.files[0]);
    }
  });

  clearFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.value = "";
    selectedFilePill.style.display = "none";
  });

  function displaySelectedFile(file) {
    selectedFileName.textContent = file.name;
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    selectedFileSize.textContent = `${sizeMb} MB`;
    selectedFilePill.style.display = "inline-flex";
  }

  // Toast Helper
  function showToast(message, duration = 3000) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => {
      toast.classList.remove("show");
    }, duration);
  }

  // Engine Switcher Logic
  const engineWhisper = document.getElementById("engineWhisper");
  const engineGemini = document.getElementById("engineGemini");
  const engineWhisperLabel = document.getElementById("engineWhisperLabel");
  const engineGeminiLabel = document.getElementById("engineGeminiLabel");
  const geminiKeyBox = document.getElementById("geminiKeyBox");
  const whisperSettingsGrid = document.getElementById("whisperSettingsGrid");

  function updateEngineUI() {
    if (engineGemini.checked) {
      engineGeminiLabel.classList.add("active");
      engineWhisperLabel.classList.remove("active");
      geminiKeyBox.style.display = "block";
    } else {
      engineWhisperLabel.classList.add("active");
      engineGeminiLabel.classList.remove("active");
      geminiKeyBox.style.display = "none";
    }
  }

  engineWhisper.addEventListener("change", updateEngineUI);
  engineGemini.addEventListener("change", updateEngineUI);

  // Form Submit -> Start Job
  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!fileInput.files || fileInput.files.length === 0) {
      showToast("Please select a video or audio file first.");
      return;
    }

    const file = fileInput.files[0];
    const engine = engineGemini.checked ? "gemini" : "whisper";
    const apiKey = document.getElementById("geminiApiKey").value.trim();

    if (engine === "gemini" && !apiKey) {
      showToast("Please enter your Google Gemini API key or switch to Local Whisper.");
      return;
    }

    const modelSize = document.getElementById("modelSelect").value;
    const language = document.getElementById("langSelect").value;
    const customPrompt = document.getElementById("customPrompt").value;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("engine", engine);
    formData.append("model_size", modelSize);
    formData.append("language", language);
    formData.append("custom_prompt", customPrompt);
    formData.append("api_key", apiKey);

    startBtn.disabled = true;
    startBtn.innerHTML = `
      <span style="display:inline-block;animation:spin 1s linear infinite;">⏳</span>
      Uploading & Initializing...
    `;

    progressCard.style.display = "block";
    resultsWorkspace.style.display = "none";
    progressCard.scrollIntoView({ behavior: "smooth" });

    updateProgressUI(5, "Uploading file...", "Transferring to local transcription engine...");

    try {
      const resp = await fetch("/api/transcribe", {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        throw new Error(`Upload failed with status ${resp.status}`);
      }

      const data = await resp.json();
      currentJobId = data.job_id;
      startPollingProgress(currentJobId);
    } catch (err) {
      console.error(err);
      showToast(`Error: ${err.message}`);
      resetFormState();
    }
  });

  function startPollingProgress(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/job/${jobId}`);
        if (!resp.ok) return;

        const job = await resp.json();
        const progress = job.progress || 0;
        const msg = job.message || "Working...";

        updateProgressUI(progress, formatStatusTitle(job.status), msg);

        if (job.status === "completed") {
          clearInterval(pollInterval);
          onJobCompleted(job);
        } else if (job.status === "failed") {
          clearInterval(pollInterval);
          showToast(`Transcription Failed: ${job.error || "Unknown error"}`);
          resetFormState();
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1200);
  }

  function formatStatusTitle(status) {
    switch (status) {
      case "extracting_audio": return "Phase 1: Extracting Audio";
      case "loading_model": return "Phase 2: Initializing Whisper AI";
      case "transcribing": return "Phase 3: High-Accuracy Tagalog/Taglish Transcription";
      case "completed": return "Transcription Complete!";
      default: return "Processing Video...";
    }
  }

  function updateProgressUI(pct, title, details) {
    progressPercent.textContent = `${pct}%`;
    progressBarFill.style.width = `${pct}%`;
    progressPhase.textContent = title;
    progressDetails.textContent = details;

    // Step dots
    step1.classList.toggle("done", pct > 20);
    step1.classList.toggle("active", pct <= 20);

    step2.classList.toggle("done", pct > 40);
    step2.classList.toggle("active", pct > 20 && pct <= 40);

    step3.classList.toggle("done", pct >= 95);
    step3.classList.toggle("active", pct > 40 && pct < 95);

    step4.classList.toggle("done", pct === 100);
    step4.classList.toggle("active", pct >= 95 && pct < 100);
  }

  function resetFormState() {
    startBtn.disabled = false;
    startBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:18px;height:18px;">
        <polygon points="5 3 19 12 5 21 5 3"/>
      </svg>
      Start High-Accuracy Transcription
    `;
  }

  function onJobCompleted(job) {
    resetFormState();
    showToast("Transcription completed successfully!");

    currentSegments = job.segments || [];

    // Set video src
    videoPlayer.src = job.video_url;
    const langCode = (job.detected_language || "tl").toLowerCase();
    const langFlag = langCode === "tl" ? "🇵🇭 Tagalog" : (langCode === "en" ? "🇺🇸 English" : langCode.toUpperCase());
    const conf = job.language_probability ? ` (${Math.round(job.language_probability * 100)}%)` : "";
    metaLang.textContent = `${langFlag}${conf}`;
    metaDuration.textContent = job.duration ? `${job.duration}s` : "-";
    metaSegmentsCount.textContent = currentSegments.length;

    renderSegments(currentSegments);

    resultsWorkspace.style.display = "grid";
    resultsWorkspace.scrollIntoView({ behavior: "smooth" });
  }

  // Render Transcript Segments
  function renderSegments(segments) {
    segmentsList.innerHTML = "";

    if (segments.length === 0) {
      segmentsList.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-subtle);">No speech segments detected.</div>`;
      return;
    }

    segments.forEach((seg, index) => {
      const item = document.createElement("div");
      item.className = "segment-item";
      item.dataset.index = index;
      item.dataset.start = seg.start;
      item.dataset.end = seg.end;

      item.innerHTML = `
        <div class="segment-header">
          <span class="segment-time" title="Click to jump">${seg.start_fmt} ➔ ${seg.end_fmt}</span>
          <span style="font-size:0.75rem;color:var(--text-subtle);">#${index + 1}</span>
        </div>
        <textarea class="segment-text-input" rows="2">${escapeHtml(seg.text)}</textarea>
      `;

      // Jump video when clicking timestamp header
      item.querySelector(".segment-time").addEventListener("click", (e) => {
        e.stopPropagation();
        videoPlayer.currentTime = seg.start;
        videoPlayer.play();
      });

      // Update in-memory segment text upon edit
      const textarea = item.querySelector(".segment-text-input");
      textarea.addEventListener("input", () => {
        currentSegments[index].text = textarea.value;
      });

      segmentsList.appendChild(item);
    });
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Real-time synchronization during video playback
  videoPlayer.addEventListener("timeupdate", () => {
    const curTime = videoPlayer.currentTime;
    let foundActive = false;

    const items = segmentsList.querySelectorAll(".segment-item");
    items.forEach((item) => {
      const start = parseFloat(item.dataset.start);
      const end = parseFloat(item.dataset.end);

      if (curTime >= start && curTime <= end) {
        if (!item.classList.contains("active")) {
          // Remove active from others
          items.forEach(el => el.classList.remove("active"));
          item.classList.add("active");
          // Smooth scroll active segment into view
          item.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        activeSubOverlay.textContent = item.querySelector(".segment-text-input").value;
        activeSubOverlay.style.display = "block";
        foundActive = true;
      }
    });

    if (!foundActive) {
      activeSubOverlay.style.display = "none";
    }
  });

  // Video Controls
  jumpBackBtn.addEventListener("click", () => {
    videoPlayer.currentTime = Math.max(0, videoPlayer.currentTime - 5);
  });

  jumpForwardBtn.addEventListener("click", () => {
    videoPlayer.currentTime = Math.min(videoPlayer.duration || 0, videoPlayer.currentTime + 5);
  });

  togglePlayBtn.addEventListener("click", () => {
    if (videoPlayer.paused) {
      videoPlayer.play();
    } else {
      videoPlayer.pause();
    }
  });

  playbackSpeed.addEventListener("change", () => {
    videoPlayer.playbackRate = parseFloat(playbackSpeed.value);
  });

  // Transcript Search Filter
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.toLowerCase().trim();
    const items = segmentsList.querySelectorAll(".segment-item");

    items.forEach((item) => {
      const text = item.querySelector(".segment-text-input").value.toLowerCase();
      if (!query || text.includes(query)) {
        item.style.display = "block";
      } else {
        item.style.display = "none";
      }
    });
  });

  // Copy Full Transcript
  copyAllBtn.addEventListener("click", () => {
    if (currentSegments.length === 0) return;
    const fullText = currentSegments.map(s => `[${s.start_fmt} - ${s.end_fmt}] ${s.text}`).join("\n\n");
    navigator.clipboard.writeText(fullText).then(() => {
      showToast("Transcript copied to clipboard!");
    });
  });

  // Save Edits to Server
  saveEditsBtn.addEventListener("click", async () => {
    if (!currentJobId) return;

    try {
      const resp = await fetch(`/api/job/${currentJobId}/segments`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segments: currentSegments })
      });

      if (resp.ok) {
        showToast("Edits saved! Exported files are updated.");
      } else {
        showToast("Failed to save edits.");
      }
    } catch (e) {
      showToast(`Save error: ${e.message}`);
    }
  });

  // Polish Words Handler
  polishWordsBtn.addEventListener("click", async () => {
    if (!currentJobId) {
      showToast("No active transcription to polish.");
      return;
    }

    const apiKey = document.getElementById("geminiApiKey") ? document.getElementById("geminiApiKey").value.trim() : "";
    
    polishWordsBtn.disabled = true;
    const origHTML = polishWordsBtn.innerHTML;
    polishWordsBtn.innerHTML = `<span>⏳</span> Polishing...`;

    try {
      const resp = await fetch(`/api/job/${currentJobId}/polish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey })
      });

      if (!resp.ok) {
        throw new Error("Failed to polish words");
      }

      const data = await resp.json();
      currentSegments = data.segments || [];
      renderSegments(currentSegments);
      showToast(`✨ ${data.count || 0} segments polished! Stutters & grammar cleaned.`);
    } catch (err) {
      console.error(err);
      showToast(`Polish error: ${err.message}`);
    } finally {
      polishWordsBtn.disabled = false;
      polishWordsBtn.innerHTML = origHTML;
    }
  });

  // Export Menu Toggle
  exportMenuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    exportMenu.classList.toggle("show");
  });

  document.addEventListener("click", () => {
    exportMenu.classList.remove("show");
  });

  // Export Downloads
  document.querySelectorAll(".export-opt").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.preventDefault();
      if (!currentJobId) {
        showToast("No active transcription to export.");
        return;
      }
      const fmt = opt.dataset.format;
      window.location.href = `/api/job/${currentJobId}/export/${fmt}`;
    });
  });

});
