// 页面元素引用：语音生成表单、音频识别表单以及字幕展示区
const generationForm = document.getElementById("generation-form");
const transcriptionForm = document.getElementById("transcription-form");
const audioFileInput = document.getElementById("audio-file");
const audioUrlInput = document.getElementById("audio-url");
const transcriptsList = document.getElementById("transcripts-list");
const transcriptSelect = document.getElementById("transcript-select");
const editTranscriptSelect = document.getElementById("edit-transcript-select");
const loadSelectedTranscriptButton = document.getElementById("load-selected-transcript");
const editableSrtFileInput = document.getElementById("editable-srt-file");
const editorPanel = document.getElementById("editor-panel");
const segmentsEditor = document.getElementById("segments-editor");
const editorMessage = document.getElementById("editor-message");
const editorSourceLabel = document.getElementById("editor-source-label");
const saveEditedButton = document.getElementById("save-edited-transcript");
const selectedTranscriptInput = document.getElementById("selected-transcript-id");
const transcriptionResult = document.getElementById("transcription-result");
const transcriptionMessage = document.getElementById("transcription-message");
const transcriptViewer = document.getElementById("transcript-viewer");

const statusPanel = document.getElementById("status-panel");
const progressBar = document.getElementById("progress-bar");
const statusMessage = document.getElementById("status-message");
const downloadLink = document.getElementById("download-link");

let pollTimer = null;
let editableSegments = [];
let editingSourceTranscriptId = "";
let editingFilename = "";

function resetStatus() {
  // 在用户重新提交任务前，清空轮询器与提示信息
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  progressBar.style.width = "0%";
  statusMessage.textContent = "";
  downloadLink.classList.add("hidden");
  downloadLink.textContent = "";
}

function formatSeconds(value) {
  const seconds = Number(value) || 0;
  return seconds.toFixed(2);
}

function srtTimeToSeconds(timeText) {
  const [hms, ms] = timeText.split(",");
  const parts = hms.split(":").map((part) => parseInt(part, 10));
  if (parts.length !== 3 || Number.isNaN(parts[0]) || Number.isNaN(parts[1]) || Number.isNaN(parts[2])) {
    return 0;
  }
  const millis = parseInt(ms, 10);
  if (Number.isNaN(millis)) {
    return 0;
  }
  return parts[0] * 3600 + parts[1] * 60 + parts[2] + millis / 1000;
}

function parseSrtText(content) {
  const normalized = content.replace(/\r\n/g, "\n");
  const blocks = normalized.split(/\n\n+/).filter(Boolean);
  const parsed = [];

  blocks.forEach((block) => {
    const lines = block.split("\n").filter(Boolean);
    if (lines.length < 2) {
      return;
    }

    const timeMatch = lines[1].match(/(?<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?<end>\d{2}:\d{2}:\d{2},\d{3})/);
    if (!timeMatch || !timeMatch.groups) {
      return;
    }

    const start = srtTimeToSeconds(timeMatch.groups.start);
    const end = srtTimeToSeconds(timeMatch.groups.end);
    const textBody = lines.slice(2).join("\n");
    const [firstLine, ...rest] = textBody.split(":");
    let speaker = "Narrator";
    let body = textBody;
    const metadata = {};

    if (rest.length) {
      speaker = firstLine.trim() || "Narrator";
      body = rest.join(":").trim();
    }

    if (speaker.includes("|")) {
      const parts = speaker.split("|").map((item) => item.trim()).filter(Boolean);
      speaker = parts.shift() || "Narrator";
      parts.forEach((token) => {
        const [key, value] = token.split("=");
        if (key && value) {
          metadata[key.trim().toLowerCase()] = value.trim();
        }
      });
    }

    parsed.push({
      speaker,
      text: body,
      start,
      end,
      emotion: metadata.emotion || null,
      tone: metadata.tone || null,
      gender: metadata.gender || null,
    });
  });

  return parsed;
}

function applyTimingDelta(startIndex, deltaSeconds) {
  if (!deltaSeconds) {
    return;
  }
  for (let i = startIndex; i < editableSegments.length; i += 1) {
    editableSegments[i].start = Math.max(0, editableSegments[i].start + deltaSeconds);
    editableSegments[i].end = Math.max(editableSegments[i].start, editableSegments[i].end + deltaSeconds);
  }
}

function updateSegmentTiming(index, newStart, newDuration) {
  const segment = editableSegments[index];
  const safeStart = Math.max(0, Number.isFinite(newStart) ? newStart : segment.start);
  const duration = Math.max(0, Number.isFinite(newDuration) ? newDuration : segment.end - segment.start);
  const previousEnd = segment.end;

  segment.start = safeStart;
  segment.end = safeStart + duration;

  const delta = segment.end - previousEnd;
  if (delta !== 0) {
    applyTimingDelta(index + 1, delta);
  }
}

function setEditableSegments(segments, sourceLabel, sourceId, filename) {
  editableSegments = segments
    .map((segment) => ({
      speaker: segment.speaker || "Narrator",
      text: segment.text || "",
      start: Number(segment.start) || 0,
      end: Number(segment.end) || Number(segment.start) || 0,
      emotion: segment.emotion || "",
      tone: segment.tone || "",
      gender: segment.gender || "",
    }))
    .sort((a, b) => a.start - b.start);

  editingSourceTranscriptId = sourceId || "";
  editingFilename = filename || sourceLabel || "edited_transcript.srt";

  editorSourceLabel.textContent = sourceLabel;
  editorMessage.textContent = "";
  editorPanel.classList.remove("hidden");
  renderSegmentsEditor();
}

function renderSegmentsEditor() {
  segmentsEditor.innerHTML = "";

  if (!editableSegments.length) {
    const empty = document.createElement("p");
    empty.textContent = "当前没有可编辑的字幕片段，请先选择或上传字幕。";
    segmentsEditor.appendChild(empty);
    return;
  }

  editableSegments.forEach((segment, index) => {
    const article = document.createElement("article");

    const header = document.createElement("header");
    const title = document.createElement("h4");
    title.textContent = `片段 ${index + 1}`;
    header.appendChild(title);
    article.appendChild(header);

    const timingRow = document.createElement("div");
    timingRow.classList.add("grid");

    const startField = document.createElement("label");
    startField.textContent = "开始时间（秒）";
    const startInput = document.createElement("input");
    startInput.type = "number";
    startInput.step = "0.1";
    startInput.value = formatSeconds(segment.start);
    startInput.addEventListener("change", () => {
      const nextDuration = segment.end - segment.start;
      updateSegmentTiming(index, parseFloat(startInput.value), nextDuration);
      renderSegmentsEditor();
    });
    startField.appendChild(startInput);

    const durationField = document.createElement("label");
    durationField.textContent = "时长（秒）";
    const durationInput = document.createElement("input");
    durationInput.type = "number";
    durationInput.step = "0.1";
    durationInput.min = "0";
    durationInput.value = formatSeconds(segment.end - segment.start);
    durationInput.addEventListener("change", () => {
      updateSegmentTiming(index, segment.start, parseFloat(durationInput.value));
      renderSegmentsEditor();
    });
    durationField.appendChild(durationInput);

    const endField = document.createElement("p");
    endField.textContent = `结束时间：${formatSeconds(segment.end)} 秒`;

    timingRow.appendChild(startField);
    timingRow.appendChild(durationField);
    timingRow.appendChild(endField);
    article.appendChild(timingRow);

    const speakerField = document.createElement("label");
    speakerField.textContent = "说话人";
    const speakerInput = document.createElement("input");
    speakerInput.value = segment.speaker;
    speakerInput.addEventListener("input", () => {
      segment.speaker = speakerInput.value;
    });
    speakerField.appendChild(speakerInput);
    article.appendChild(speakerField);

    const emotionRow = document.createElement("div");
    emotionRow.classList.add("grid");

    const emotionField = document.createElement("label");
    emotionField.textContent = "情感表达";
    const emotionInput = document.createElement("input");
    emotionInput.value = segment.emotion;
    emotionInput.addEventListener("input", () => {
      segment.emotion = emotionInput.value;
    });
    emotionField.appendChild(emotionInput);

    const toneField = document.createElement("label");
    toneField.textContent = "语气/音色";
    const toneInput = document.createElement("input");
    toneInput.value = segment.tone;
    toneInput.addEventListener("input", () => {
      segment.tone = toneInput.value;
    });
    toneField.appendChild(toneInput);

    const genderField = document.createElement("label");
    genderField.textContent = "性别标记（可选）";
    const genderInput = document.createElement("input");
    genderInput.value = segment.gender;
    genderInput.addEventListener("input", () => {
      segment.gender = genderInput.value;
    });
    genderField.appendChild(genderInput);

    emotionRow.appendChild(emotionField);
    emotionRow.appendChild(toneField);
    emotionRow.appendChild(genderField);
    article.appendChild(emotionRow);

    const textField = document.createElement("label");
    textField.textContent = "台词正文";
    const textArea = document.createElement("textarea");
    textArea.value = segment.text;
    textArea.addEventListener("input", () => {
      segment.text = textArea.value;
    });
    textField.appendChild(textArea);
    article.appendChild(textField);

    segmentsEditor.appendChild(article);
  });
}

async function pollStatus(jobId) {
  // 周期性获取后台任务状态，更新进度条
  pollTimer = setInterval(async () => {
    try {
      const response = await fetch(`/status/${jobId}`);
      if (!response.ok) {
        throw new Error("无法获取任务状态");
      }
      const data = await response.json();
      progressBar.style.width = `${Math.floor(data.progress || 0)}%`;
      statusMessage.textContent = data.message || "处理中";

      if (data.status === "completed") {
        clearInterval(pollTimer);
        pollTimer = null;
        if (data.download_url) {
          downloadLink.textContent = "";
          const link = document.createElement("a");
          link.href = data.download_url;
          link.download = "";
          link.textContent = "下载生成的 MP3";
          downloadLink.appendChild(link);
          downloadLink.classList.remove("hidden");
        }
      } else if (data.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        statusMessage.textContent = `任务失败：${data.message || "未知错误"}`;
      }
    } catch (error) {
      clearInterval(pollTimer);
      pollTimer = null;
      statusMessage.textContent = `状态更新失败：${error.message}`;
    }
  }, 1500);
}

function renderTranscripts(transcripts) {
  // 渲染历史字幕列表，便于复用
  transcriptsList.innerHTML = "";

  if (!transcripts.length) {
    const emptyMessage = document.createElement("p");
    emptyMessage.textContent = "暂无字幕文件，您可以先上传音频进行识别。";
    transcriptsList.appendChild(emptyMessage);
    return;
  }

  transcripts.forEach((item) => {
    const article = document.createElement("article");
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "";
    const speakers = item.speakers && item.speakers.length ? item.speakers.join("、") : "未识别";
    const duration = item.duration_seconds ? `${item.duration_seconds.toFixed(1)}s` : "-";

    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = item.original_filename || item.id;
    header.appendChild(title);
    article.appendChild(header);

    const createdParagraph = document.createElement("p");
    createdParagraph.textContent = `创建时间：${createdAt}`;
    article.appendChild(createdParagraph);

    const speakersParagraph = document.createElement("p");
    speakersParagraph.textContent = `角色：${speakers}`;
    article.appendChild(speakersParagraph);

    const durationParagraph = document.createElement("p");
    durationParagraph.textContent = `时长：${duration}`;
    article.appendChild(durationParagraph);

    const footer = document.createElement("footer");
    footer.classList.add("grid");

    const downloadLink = document.createElement("a");
    downloadLink.classList.add("secondary");
    downloadLink.href = item.download_url;
    downloadLink.download = "";
    downloadLink.textContent = "下载 SRT";
    footer.appendChild(downloadLink);

    const viewButton = document.createElement("button");
    viewButton.type = "button";
    viewButton.dataset.action = "view";
    viewButton.dataset.id = item.id;
    viewButton.textContent = "查看内容";
    footer.appendChild(viewButton);

    const useButton = document.createElement("button");
    useButton.type = "button";
    useButton.dataset.action = "use";
    useButton.dataset.id = item.id;
    useButton.textContent = "用于语音合成";
    footer.appendChild(useButton);

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.dataset.action = "edit";
    editButton.dataset.id = item.id;
    editButton.textContent = "编辑字幕";
    footer.appendChild(editButton);

    article.appendChild(footer);
    transcriptsList.appendChild(article);
  });
}

function updateTranscriptSelect(transcripts) {
  // 刷新下拉框选项，保持用户之前的选择
  const previousValue = transcriptSelect.value;
  const previousEditValue = editTranscriptSelect.value;
  transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  editTranscriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';

  transcripts.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "";
    option.textContent = `${item.original_filename || item.id} (${createdAt})`;
    transcriptSelect.appendChild(option);

    const editOption = document.createElement("option");
    editOption.value = item.id;
    editOption.textContent = option.textContent;
    editTranscriptSelect.appendChild(editOption);
  });

  if (previousValue) {
    transcriptSelect.value = previousValue;
  }
  if (previousEditValue) {
    editTranscriptSelect.value = previousEditValue;
  }
  selectedTranscriptInput.value = transcriptSelect.value;
}

async function fetchTranscripts() {
  // 从后端获取最新字幕文件列表
  try {
    const response = await fetch("/transcripts");
    if (!response.ok) {
      throw new Error("接口返回异常");
    }
    const data = await response.json();
    const transcripts = data.transcripts || [];
    renderTranscripts(transcripts);
    updateTranscriptSelect(transcripts);
  } catch (error) {
    transcriptsList.innerHTML = "";
    const errorParagraph = document.createElement("p");
    errorParagraph.classList.add("contrast");
    errorParagraph.textContent = `加载字幕列表失败：${error.message}`;
    transcriptsList.appendChild(errorParagraph);
    transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  }
}

async function loadTranscriptIntoEditor(transcriptId) {
  if (!transcriptId) {
    editorMessage.textContent = "请选择需要编辑的字幕。";
    return;
  }

  try {
    const response = await fetch(`/transcripts/${encodeURIComponent(transcriptId)}`);
    if (!response.ok) {
      throw new Error("无法加载字幕详情");
    }
    const data = await response.json();
    const segments = Array.isArray(data.segments) ? data.segments : [];
    if (!segments.length && typeof data.srt === "string") {
      setEditableSegments(parseSrtText(data.srt), data.original_filename || data.id, transcriptId, data.original_filename);
      return;
    }
    setEditableSegments(segments, data.original_filename || data.id, transcriptId, data.original_filename);
  } catch (error) {
    editorMessage.textContent = `加载字幕失败：${error.message}`;
    editorPanel.classList.remove("hidden");
  }
}

async function saveEditedTranscript() {
  if (!editableSegments.length) {
    editorMessage.textContent = "当前没有需要保存的字幕片段。";
    return;
  }

  const payload = {
    original_filename: editingFilename,
    source_transcript_id: editingSourceTranscriptId || null,
    segments: editableSegments.map((segment) => ({
      speaker: segment.speaker || "Narrator",
      text: segment.text || "",
      start: Number(segment.start) || 0,
      end: Number(segment.end) || 0,
      emotion: segment.emotion || "",
      tone: segment.tone || "",
      gender: segment.gender || "",
    })),
  };

  try {
    const response = await fetch("/transcripts/save", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "保存失败");
    }

    const data = await response.json();
    const metadata = data.metadata || {};
    const transcriptId = data.transcript_id || metadata.id || editingSourceTranscriptId || "";
    const label = metadata.original_filename || metadata.id || transcriptId || "edited_transcript.srt";

    editingSourceTranscriptId = transcriptId;
    editingFilename = metadata.original_filename || editingFilename;

    const refreshedSegments = Array.isArray(metadata.segments) ? metadata.segments : [];
    if (refreshedSegments.length) {
      setEditableSegments(refreshedSegments, label, transcriptId, editingFilename);
    } else if (typeof metadata.srt === "string") {
      setEditableSegments(parseSrtText(metadata.srt), label, transcriptId, editingFilename);
    }

    editorMessage.textContent = "字幕已保存，您可以下载或继续查看最新版本。";
    if (metadata.download_url) {
      const link = document.createElement("a");
      link.href = metadata.download_url;
      link.download = "";
      link.textContent = "下载新字幕";
      editorMessage.textContent = "字幕已保存，";
      editorMessage.appendChild(link);
      editorMessage.appendChild(document.createTextNode("，或继续调整。"));
    }

    await fetchTranscripts();
    if (transcriptId) {
      transcriptSelect.value = transcriptId;
      editTranscriptSelect.value = transcriptId;
      selectedTranscriptInput.value = transcriptId;
    }
  } catch (error) {
    editorMessage.textContent = `保存失败：${error.message}`;
  }
}

// 监听字幕卡片上的按钮，支持查看与复用字幕
transcriptsList.addEventListener("click", async (event) => {
  const target = event.target.closest("button[data-action]");
  if (!target) {
    return;
  }

  const action = target.dataset.action;
  const transcriptId = target.dataset.id;

  if (!action || !transcriptId) {
    return;
  }

  if (action === "view") {
    try {
      const response = await fetch(`/transcripts/${transcriptId}`);
      if (!response.ok) {
        throw new Error("无法获取字幕内容");
      }
      const data = await response.json();
      transcriptionResult.classList.remove("hidden");
      transcriptionMessage.textContent = `来源：${data.original_filename || data.id}，`;
      const downloadAnchor = document.createElement("a");
      downloadAnchor.href = data.download_url;
      downloadAnchor.download = "";
      downloadAnchor.textContent = "下载";
      transcriptionMessage.appendChild(downloadAnchor);
      transcriptViewer.textContent = data.srt || "";
      selectedTranscriptInput.value = transcriptId;
      transcriptSelect.value = transcriptId;
    } catch (error) {
      transcriptionResult.classList.remove("hidden");
      transcriptionMessage.textContent = `加载失败：${error.message}`;
      transcriptViewer.textContent = "";
    }
  } else if (action === "use") {
    selectedTranscriptInput.value = transcriptId;
    transcriptSelect.value = transcriptId;
    transcriptionResult.classList.remove("hidden");
    transcriptionMessage.textContent = "已选择该字幕用于语音生成，请在下方配置参数并提交。";
    transcriptViewer.textContent = "";
    generationForm.scrollIntoView({ behavior: "smooth" });
  } else if (action === "edit") {
    loadTranscriptIntoEditor(transcriptId);
    editorPanel.scrollIntoView({ behavior: "smooth" });
  }
});

transcriptSelect.addEventListener("change", (event) => {
  selectedTranscriptInput.value = event.target.value;
});

loadSelectedTranscriptButton.addEventListener("click", () => {
  const chosen = editTranscriptSelect.value;
  loadTranscriptIntoEditor(chosen);
});

editableSrtFileInput.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    const content = reader.result || "";
    const text = typeof content === "string" ? content : "";
    const parsed = parseSrtText(text);
    if (!parsed.length) {
      editorMessage.textContent = "无法从上传的文件解析出字幕片段，请确认格式正确。";
      editorPanel.classList.remove("hidden");
      return;
    }
    setEditableSegments(parsed, file.name, "", file.name);
    editorPanel.scrollIntoView({ behavior: "smooth" });
  };
  reader.readAsText(file, "utf-8");
});

saveEditedButton.addEventListener("click", () => {
  saveEditedTranscript();
});

// 上传音频并调用语音识别接口
transcriptionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const selectedFile = audioFileInput?.files?.[0] || null;
  const audioUrl = (audioUrlInput?.value || "").trim();

  if (!selectedFile && !audioUrl) {
    transcriptionResult.classList.remove("hidden");
    transcriptionMessage.textContent = "请上传音频文件或填写音频 URL。";
    transcriptViewer.textContent = "";
    return;
  }

  const formData = new FormData();
  if (selectedFile) {
    formData.append("file", selectedFile);
  }
  if (audioUrl) {
    formData.append("audio_url", audioUrl);
  }
  const configField = transcriptionForm.elements.namedItem("config");
  if (configField && typeof configField.value === "string") {
    const configValue = configField.value.trim();
    if (configValue) {
      formData.append("config", configValue);
    }
  }
  transcriptionResult.classList.remove("hidden");
  transcriptionMessage.textContent = "正在上传并识别，请稍候...";
  transcriptViewer.textContent = "";

  try {
    const response = await fetch("/transcribe", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "识别失败");
    }

    const data = await response.json();
    transcriptionMessage.textContent = "字幕已生成，可 ";
    const downloadAnchor = document.createElement("a");
    downloadAnchor.href = data.download_url;
    downloadAnchor.download = "";
    downloadAnchor.textContent = "下载 SRT 文件";
    transcriptionMessage.appendChild(downloadAnchor);
    transcriptionMessage.appendChild(document.createTextNode("。"));
    transcriptViewer.textContent = data.srt || "";
    await fetchTranscripts();
    transcriptSelect.value = data.transcript_id;
    selectedTranscriptInput.value = data.transcript_id;
  } catch (error) {
    transcriptionMessage.textContent = `识别失败：${error.message}`;
    transcriptViewer.textContent = "";
  }
});

// 提交语音合成任务，可以上传新的 SRT 或复用历史字幕
generationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetStatus();

  const fileInput = document.getElementById("srt-file");
  const configInput = document.getElementById("config-json");
  const transcriptId = transcriptSelect.value || selectedTranscriptInput.value;

  if (!configInput.value.trim()) {
    statusPanel.classList.remove("hidden");
    statusMessage.textContent = "请填写角色与接口配置。";
    return;
  }

  if (!fileInput.files.length && !transcriptId) {
    statusPanel.classList.remove("hidden");
    statusMessage.textContent = "请上传字幕文件或选择历史字幕。";
    return;
  }

  statusPanel.classList.remove("hidden");
  statusMessage.textContent = "正在创建语音生成任务...";

  try {
    let response;
    if (fileInput.files.length) {
      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("config", configInput.value);
      response = await fetch("/generate", {
        method: "POST",
        body: formData,
      });
    } else {
      const formData = new FormData();
      formData.append("config", configInput.value);
      response = await fetch(`/transcripts/${encodeURIComponent(transcriptId)}/generate`, {
        method: "POST",
        body: formData,
      });
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "提交失败");
    }

    const data = await response.json();
    statusMessage.textContent = "任务已创建，开始处理...";
    pollStatus(data.job_id);
  } catch (error) {
    statusMessage.textContent = `提交失败：${error.message}`;
  }
});

fetchTranscripts();
