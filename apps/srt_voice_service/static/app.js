const generationForm = document.getElementById("generation-form");
const transcriptionForm = document.getElementById("transcription-form");
const transcriptsList = document.getElementById("transcripts-list");
const transcriptSelect = document.getElementById("transcript-select");
const selectedTranscriptInput = document.getElementById("selected-transcript-id");
const transcriptionResult = document.getElementById("transcription-result");
const transcriptionMessage = document.getElementById("transcription-message");
const transcriptViewer = document.getElementById("transcript-viewer");

const statusPanel = document.getElementById("status-panel");
const progressBar = document.getElementById("progress-bar");
const statusMessage = document.getElementById("status-message");
const downloadLink = document.getElementById("download-link");

let pollTimer = null;

function resetStatus() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  progressBar.style.width = "0%";
  statusMessage.textContent = "";
  downloadLink.classList.add("hidden");
  downloadLink.innerHTML = "";
}

async function pollStatus(jobId) {
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
          downloadLink.innerHTML = `<a href="${data.download_url}" download>下载生成的 MP3</a>`;
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
  transcriptsList.innerHTML = "";

  if (!transcripts.length) {
    transcriptsList.innerHTML = "<p>暂无字幕文件，您可以先上传音频进行识别。</p>";
    return;
  }

  transcripts.forEach((item) => {
    const article = document.createElement("article");
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "";
    const speakers = item.speakers && item.speakers.length ? item.speakers.join("、") : "未识别";
    const duration = item.duration_seconds ? `${item.duration_seconds.toFixed(1)}s` : "-";

    article.innerHTML = `
      <header>
        <strong>${item.original_filename || item.id}</strong>
      </header>
      <p>创建时间：${createdAt}</p>
      <p>角色：${speakers}</p>
      <p>时长：${duration}</p>
      <footer class="grid">
        <a class="secondary" href="${item.download_url}" download>下载 SRT</a>
        <button type="button" data-action="view" data-id="${item.id}">查看内容</button>
        <button type="button" data-action="use" data-id="${item.id}">用于语音合成</button>
      </footer>
    `;
    transcriptsList.appendChild(article);
  });
}

function updateTranscriptSelect(transcripts) {
  const previousValue = transcriptSelect.value;
  transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';

  transcripts.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : "";
    option.textContent = `${item.original_filename || item.id} (${createdAt})`;
    transcriptSelect.appendChild(option);
  });

  if (previousValue) {
    transcriptSelect.value = previousValue;
  }
  selectedTranscriptInput.value = transcriptSelect.value;
}

async function fetchTranscripts() {
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
    transcriptsList.innerHTML = `<p class="contrast">加载字幕列表失败：${error.message}</p>`;
    transcriptSelect.innerHTML = '<option value="">-- 请选择已有字幕 --</option>';
  }
}

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
      transcriptionMessage.innerHTML = `来源：${data.original_filename || data.id}，<a href="${data.download_url}" download>下载</a>`;
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
  }
});

transcriptSelect.addEventListener("change", (event) => {
  selectedTranscriptInput.value = event.target.value;
});

transcriptionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(transcriptionForm);
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
    transcriptionMessage.innerHTML = `字幕已生成，可 <a href="${data.download_url}" download>下载 SRT 文件</a>。`;
    transcriptViewer.textContent = data.srt || "";
    await fetchTranscripts();
    transcriptSelect.value = data.transcript_id;
    selectedTranscriptInput.value = data.transcript_id;
  } catch (error) {
    transcriptionMessage.textContent = `识别失败：${error.message}`;
    transcriptViewer.textContent = "";
  }
});

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
