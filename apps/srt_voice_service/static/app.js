const form = document.getElementById("generation-form");
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetStatus();

  const fileInput = document.getElementById("srt-file");
  const configInput = document.getElementById("config-json");

  if (!fileInput.files.length) {
    statusMessage.textContent = "请先选择字幕文件。";
    return;
  }

  statusPanel.classList.remove("hidden");
  statusMessage.textContent = "正在上传并创建任务...";

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("config", configInput.value);

  try {
    const response = await fetch("/generate", {
      method: "POST",
      body: formData,
    });

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
