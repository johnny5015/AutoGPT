// 页面元素引用：语音生成表单、音频识别表单以及字幕展示区
const generationForm = document.getElementById("generation-form");
const transcriptionForm = document.getElementById("transcription-form");
const audioFileInput = document.getElementById("audio-file");
const audioUrlInput = document.getElementById("audio-url");
const transcriptsList = document.getElementById("transcripts-list");
const transcriptSelect = document.getElementById("transcript-select");
const editorLaunchSelect = document.getElementById("editor-launch-select");
const viewInEditorButton = document.getElementById("view-in-editor");
const editInEditorButton = document.getElementById("edit-in-editor");
const launchEditorUploadInput = document.getElementById("launch-editor-upload");
const editorLaunchMessage = document.getElementById("editor-launch-message");
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
const isEditorPage = document.body?.dataset?.page === "editor";

let pollTimer = null;
let editableSegments = [];
let editingSourceTranscriptId = "";
let editingFilename = "";
let currentSegmentPage = 1;

const SEGMENTS_PER_PAGE = 40;

function openEditorPage(transcriptId, extraParams = {}) {
  const editorUrl = new URL("/editor", window.location.origin);
  if (transcriptId) {
    editorUrl.searchParams.set("transcript_id", transcriptId);
  }

  Object.entries(extraParams || {}).forEach(([key, value]) => {
    if (value) {
      editorUrl.searchParams.set(key, value);
    }
  });

  window.open(editorUrl.toString(), "_blank", "noopener,noreferrer");
}

function setEditorLaunchMessage(text) {
  if (editorLaunchMessage) {
    editorLaunchMessage.textContent = text;
  }
}

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

function secondsToSrtTime(value) {
  const totalMillis = Math.max(0, Math.round((Number(value) || 0) * 1000));
  const hours = Math.floor(totalMillis / 3600000);
  const minutes = Math.floor((totalMillis % 3600000) / 60000);
  const seconds = Math.floor((totalMillis % 60000) / 1000);
  const milliseconds = totalMillis % 1000;

  const pad = (num, size) => String(num).padStart(size, "0");
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)},${pad(milliseconds, 3)}`;
}

function segmentDuration(segment) {
  const startValue = Number(segment.start) || 0;
  const endValue = Number(segment.end) || 0;
  return Math.max(0, endValue - startValue);
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

function realignTimelineFrom(index) {
  if (!editableSegments.length) {
    return;
  }
  const startIndex = Math.max(0, index);
  for (let i = startIndex; i < editableSegments.length; i += 1) {
    const baseStart = i === 0 ? Math.max(0, editableSegments[0].start || 0) : editableSegments[i - 1].end;
    const duration = segmentDuration(editableSegments[i]);
    editableSegments[i].start = baseStart;
    editableSegments[i].end = baseStart + duration;
  }
}

function updateSegmentTiming(index, newStart, newDuration) {
  const segment = editableSegments[index];
  const safeStart = Math.max(0, Number.isFinite(newStart) ? newStart : segment.start);
  const duration = Math.max(0, Number.isFinite(newDuration) ? newDuration : segmentDuration(segment));

  segment.start = safeStart;
  segment.end = safeStart + duration;
  realignTimelineFrom(index);
}

function setEditableSegments(segments, sourceLabel, sourceId, filename) {
  if (!segmentsEditor || !editorPanel) {
    return;
  }
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

  realignTimelineFrom(0);
  editingSourceTranscriptId = sourceId || "";
  editingFilename = filename || sourceLabel || "edited_transcript.srt";
  currentSegmentPage = 1;

  editorSourceLabel.textContent = sourceLabel;
  editorMessage.textContent = "";
  editorPanel.classList.remove("hidden");
  renderSegmentsEditor();
}

function createPaginationControls(totalPages) {
  const pagination = document.createElement("div");
  pagination.classList.add("segment-pagination");

  const info = document.createElement("span");
  info.textContent = `第 ${currentSegmentPage} / ${totalPages} 页（共 ${editableSegments.length} 条）`;
  pagination.appendChild(info);

  const actions = document.createElement("div");
  actions.classList.add("segment-pagination-actions");

  const prevButton = document.createElement("button");
  prevButton.type = "button";
  prevButton.textContent = "上一页";
  prevButton.disabled = currentSegmentPage === 1;
  prevButton.addEventListener("click", () => {
    currentSegmentPage = Math.max(1, currentSegmentPage - 1);
    renderSegmentsEditor();
  });

  const nextButton = document.createElement("button");
  nextButton.type = "button";
  nextButton.textContent = "下一页";
  nextButton.disabled = currentSegmentPage >= totalPages;
  nextButton.addEventListener("click", () => {
    currentSegmentPage = Math.min(totalPages, currentSegmentPage + 1);
    renderSegmentsEditor();
  });

  const realignButton = document.createElement("button");
  realignButton.type = "button";
  realignButton.classList.add("secondary");
  realignButton.textContent = "重新计算时间轴";
  realignButton.addEventListener("click", () => {
    realignTimelineFrom(0);
    renderSegmentsEditor();
  });

  const jumpField = document.createElement("label");
  jumpField.classList.add("segment-jump");
  jumpField.textContent = "跳转页码";
  const jumpInput = document.createElement("input");
  jumpInput.type = "number";
  jumpInput.min = "1";
  jumpInput.max = String(totalPages);
  jumpInput.value = String(currentSegmentPage);
  jumpInput.addEventListener("change", () => {
    const desired = Math.max(1, Math.min(totalPages, parseInt(jumpInput.value, 10) || 1));
    currentSegmentPage = desired;
    renderSegmentsEditor();
  });
  jumpField.appendChild(jumpInput);

  actions.appendChild(prevButton);
  actions.appendChild(nextButton);
  actions.appendChild(realignButton);
  actions.appendChild(jumpField);
  pagination.appendChild(actions);
  return pagination;
}

function renderSegmentsEditor() {
  if (!segmentsEditor) {
    return;
  }
  segmentsEditor.innerHTML = "";

  if (!editableSegments.length) {
    const empty = document.createElement("p");
    empty.textContent = "当前没有可编辑的字幕片段，请先选择或上传字幕。";
    segmentsEditor.appendChild(empty);
    return;
  }

  const totalPages = Math.max(1, Math.ceil(editableSegments.length / SEGMENTS_PER_PAGE));
  currentSegmentPage = Math.min(currentSegmentPage, totalPages);
  const startIndex = (currentSegmentPage - 1) * SEGMENTS_PER_PAGE;
  const endIndex = Math.min(startIndex + SEGMENTS_PER_PAGE, editableSegments.length);

  segmentsEditor.appendChild(createPaginationControls(totalPages));

  editableSegments.slice(startIndex, endIndex).forEach((segment, offset) => {
    const index = startIndex + offset;
    const article = document.createElement("article");
    article.classList.add("segment-card");

    const header = document.createElement("header");
    const title = document.createElement("h4");
    title.textContent = `片段 ${index + 1}`;

    const timingHint = document.createElement("small");
    timingHint.classList.add("segment-time");
    timingHint.textContent = `开始 ${secondsToSrtTime(segment.start)} · 结束 ${secondsToSrtTime(segment.end)}`;
    header.appendChild(title);
    header.appendChild(timingHint);
    article.appendChild(header);

    const timingRow = document.createElement("div");
    timingRow.classList.add("segment-timing");

    const startField = document.createElement("label");
    startField.textContent = "开始时间（SRT 格式）";
    const startInput = document.createElement("input");
    startInput.type = "text";
    startInput.inputMode = "numeric";
    startInput.pattern = "\\d{2}:\\d{2}:\\d{2},\\d{3}";
    startInput.placeholder = "00:00:03,500";
    startInput.value = secondsToSrtTime(segment.start);
    startInput.addEventListener("change", () => {
      const nextDuration = segmentDuration(segment);
      const parsed = startInput.value.trim();
      const useSeconds = parsed.match(/\d{2}:\d{2}:\d{2},\d{3}/)
        ? srtTimeToSeconds(parsed)
        : parseFloat(parsed);
      updateSegmentTiming(index, useSeconds, nextDuration);
      renderSegmentsEditor();
    });
    startField.appendChild(startInput);

    const durationField = document.createElement("label");
    durationField.textContent = "时长（秒）";
    const durationInput = document.createElement("input");
    durationInput.type = "number";
    durationInput.step = "0.1";
    durationInput.min = "0";
    durationInput.value = formatSeconds(segmentDuration(segment));
    durationInput.addEventListener("change", () => {
      updateSegmentTiming(index, segment.start, parseFloat(durationInput.value));
      renderSegmentsEditor();
    });
    durationField.appendChild(durationInput);

    const endField = document.createElement("p");
    endField.classList.add("segment-end");
    endField.textContent = `结束时间：${secondsToSrtTime(segment.end)}`;

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
    emotionRow.classList.add("segment-meta");

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

  segmentsEditor.appendChild(createPaginationControls(totalPages));
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
  if (!transcriptsList) {
    return;
  }
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
  const previousValue = transcriptSelect?.value || "";
  const previousEditValue = editTranscriptSelect?.value || "";
  const previousLaunchValue = editorLaunchSelect?.value || "";

  if (transcriptSelect) {
    transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  }
  if (editTranscriptSelect) {
    editTranscriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  }
  if (editorLaunchSelect) {
    editorLaunchSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  }

  transcripts.forEach((item) => {
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "";

    if (transcriptSelect) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.original_filename || item.id} (${createdAt})`;
      transcriptSelect.appendChild(option);
    }

    if (editTranscriptSelect) {
      const editOption = document.createElement("option");
      editOption.value = item.id;
      editOption.textContent = `${item.original_filename || item.id} (${createdAt})`;
      editTranscriptSelect.appendChild(editOption);
    }

    if (editorLaunchSelect) {
      const launchOption = document.createElement("option");
      launchOption.value = item.id;
      launchOption.textContent = `${item.original_filename || item.id} (${createdAt})`;
      editorLaunchSelect.appendChild(launchOption);
    }
  });

  if (previousValue && transcriptSelect) {
    transcriptSelect.value = previousValue;
  }
  if (previousEditValue && editTranscriptSelect) {
    editTranscriptSelect.value = previousEditValue;
  }
  if (previousLaunchValue && editorLaunchSelect) {
    editorLaunchSelect.value = previousLaunchValue;
  }
  if (selectedTranscriptInput && transcriptSelect) {
    selectedTranscriptInput.value = transcriptSelect.value;
  }
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
    return transcripts;
  } catch (error) {
    if (transcriptsList) {
      transcriptsList.innerHTML = "";
      const errorParagraph = document.createElement("p");
      errorParagraph.classList.add("contrast");
      errorParagraph.textContent = `加载字幕列表失败：${error.message}`;
      transcriptsList.appendChild(errorParagraph);
    }
    if (transcriptSelect) {
      transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
    }
    return [];
  }
}

async function loadTranscriptIntoEditor(transcriptId) {
  if (!transcriptId) {
    if (editorMessage) {
      editorMessage.textContent = "请选择需要编辑的字幕。";
    }
    return;
  }

  if (!segmentsEditor || !editorPanel) {
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
    if (editorMessage) {
      editorMessage.textContent = `加载字幕失败：${error.message}`;
    }
    if (editorPanel) {
      editorPanel.classList.remove("hidden");
    }
  }
}

function loadUploadedDraftFromStorage(uploadKey, filename) {
  if (!uploadKey || !segmentsEditor || !editorPanel) {
    return;
  }

  try {
    const content = localStorage.getItem(uploadKey);
    if (!content) {
      if (editorMessage) {
        editorMessage.textContent = "未找到上传的字幕内容，请重新上传。";
      }
      return;
    }

    const parsed = parseSrtText(content);
    if (!parsed.length) {
      if (editorMessage) {
        editorMessage.textContent = "上传的文件未能解析为有效字幕，请检查格式。";
      }
      return;
    }

    const label = filename || "上传的字幕";
    setEditableSegments(parsed, label, "", filename || "uploaded.srt");
    if (editorPanel) {
      editorPanel.scrollIntoView({ behavior: "smooth" });
    }
  } finally {
    localStorage.removeItem(uploadKey);
  }
}

async function saveEditedTranscript() {
  if (!segmentsEditor || !editorPanel) {
    return;
  }
  if (!editableSegments.length) {
    if (editorMessage) {
      editorMessage.textContent = "当前没有需要保存的字幕片段。";
    }
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

    if (editorMessage) {
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
    }

    await fetchTranscripts();
    if (transcriptId) {
      if (transcriptSelect) {
        transcriptSelect.value = transcriptId;
      }
      if (editTranscriptSelect) {
        editTranscriptSelect.value = transcriptId;
      }
      if (selectedTranscriptInput) {
        selectedTranscriptInput.value = transcriptId;
      }
    }
  } catch (error) {
    if (editorMessage) {
      editorMessage.textContent = `保存失败：${error.message}`;
    }
  }
}

// 监听字幕卡片上的按钮，支持查看与复用字幕
if (transcriptsList) {
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
      openEditorPage(transcriptId, { mode: "view" });
    } else if (action === "use") {
      if (selectedTranscriptInput) {
        selectedTranscriptInput.value = transcriptId;
      }
      if (transcriptSelect) {
        transcriptSelect.value = transcriptId;
      }
      if (transcriptionResult && transcriptionMessage && transcriptViewer && generationForm) {
        transcriptionResult.classList.remove("hidden");
        transcriptionMessage.textContent = "已选择该字幕用于语音生成，请在下方配置参数并提交。";
        transcriptViewer.textContent = "";
        generationForm.scrollIntoView({ behavior: "smooth" });
      }
    } else if (action === "edit") {
      openEditorPage(transcriptId);
    }
  });
}

if (transcriptSelect && selectedTranscriptInput) {
  transcriptSelect.addEventListener("change", (event) => {
    selectedTranscriptInput.value = event.target.value;
  });
}

if (viewInEditorButton && editorLaunchSelect) {
  viewInEditorButton.addEventListener("click", () => {
    const chosen = editorLaunchSelect.value;
    if (!chosen) {
      setEditorLaunchMessage("请选择需要查看的字幕文件。");
      return;
    }
    setEditorLaunchMessage("");
    openEditorPage(chosen, { mode: "view" });
  });
}

if (editInEditorButton && editorLaunchSelect) {
  editInEditorButton.addEventListener("click", () => {
    const chosen = editorLaunchSelect.value;
    if (!chosen) {
      setEditorLaunchMessage("请选择需要编辑的字幕文件。");
      return;
    }
    setEditorLaunchMessage("");
    openEditorPage(chosen);
  });
}

if (launchEditorUploadInput) {
  launchEditorUploadInput.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setEditorLaunchMessage("请选择需要上传的字幕文件。");
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const content = reader.result || "";
      const text = typeof content === "string" ? content : "";

      if (!text.trim()) {
        setEditorLaunchMessage("未能读取到文件内容，请重试或更换文件。");
        return;
      }

      const storageKey = `editor-upload-${Date.now()}`;
      try {
        localStorage.setItem(storageKey, text);
        openEditorPage("", { upload_key: storageKey, upload_name: file.name });
        setEditorLaunchMessage("已在新页面打开编辑器并带入上传的字幕内容。");
        event.target.value = "";
      } catch (error) {
        setEditorLaunchMessage(`无法暂存文件内容：${error.message}`);
      }
    };
    reader.readAsText(file, "utf-8");
  });
}

if (loadSelectedTranscriptButton && editTranscriptSelect) {
  loadSelectedTranscriptButton.addEventListener("click", () => {
    const chosen = editTranscriptSelect.value;
    loadTranscriptIntoEditor(chosen);
  });
}

if (editableSrtFileInput) {
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
        if (editorMessage) {
          editorMessage.textContent = "无法从上传的文件解析出字幕片段，请确认格式正确。";
        }
        if (editorPanel) {
          editorPanel.classList.remove("hidden");
        }
        return;
      }
      setEditableSegments(parsed, file.name, "", file.name);
      if (editorPanel) {
        editorPanel.scrollIntoView({ behavior: "smooth" });
      }
    };
    reader.readAsText(file, "utf-8");
  });
}

if (saveEditedButton) {
  saveEditedButton.addEventListener("click", () => {
    saveEditedTranscript();
  });
}

// 上传音频并调用语音识别接口
if (transcriptionForm && transcriptionResult && transcriptionMessage && transcriptViewer) {
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
      if (transcriptSelect) {
        transcriptSelect.value = data.transcript_id;
      }
      if (selectedTranscriptInput) {
        selectedTranscriptInput.value = data.transcript_id;
      }
    } catch (error) {
      transcriptionMessage.textContent = `识别失败：${error.message}`;
      transcriptViewer.textContent = "";
    }
  });
}

// 提交语音合成任务，可以上传新的 SRT 或复用历史字幕
if (generationForm && transcriptSelect && selectedTranscriptInput) {
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
}

const urlParams = new URLSearchParams(window.location.search);
const initialTranscriptId = urlParams.get("transcript_id") || "";
const initialUploadKey = urlParams.get("upload_key") || "";
const initialUploadName = urlParams.get("upload_name") || "上传的字幕.srt";

fetchTranscripts().then(() => {
  if (initialTranscriptId && editTranscriptSelect) {
    editTranscriptSelect.value = initialTranscriptId;
    loadTranscriptIntoEditor(initialTranscriptId);
  }
  if (isEditorPage && initialUploadKey) {
    loadUploadedDraftFromStorage(initialUploadKey, initialUploadName);
  }
});
