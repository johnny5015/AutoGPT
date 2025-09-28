const form = document.getElementById('generate-form');
const rolesTable = document.getElementById('roles-table').querySelector('tbody');
const addRoleBtn = document.getElementById('add-role');
const progressSection = document.getElementById('progress-section');
const progressBar = document.getElementById('progress-bar');
const statusText = document.getElementById('status-text');
const downloadLink = document.getElementById('download-link');

function serializeRoles() {
  const rows = Array.from(rolesTable.querySelectorAll('tr'));
  return rows.map((row) => {
    const [nameInput, voiceInput] = row.querySelectorAll('input');
    return { name: nameInput.value.trim(), voice_id: voiceInput.value.trim() };
  }).filter((role) => role.name && role.voice_id);
}

function addRoleRow(name = '', voiceId = '') {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input type="text" value="${name}" placeholder="主持人" required></td>
    <td><input type="text" value="${voiceId}" placeholder="voice_001" required></td>
    <td><button type="button" class="secondary">删除</button></td>
  `;
  row.querySelector('button').addEventListener('click', () => row.remove());
  rolesTable.appendChild(row);
}

addRoleBtn.addEventListener('click', () => addRoleRow());
addRoleRow('主持人', 'voice_host');
addRoleRow('嘉宾', 'voice_guest');

async function pollProgress(jobId) {
  const response = await fetch(`/progress/${jobId}`);
  if (!response.ok) {
    statusText.textContent = '查询进度失败';
    return;
  }
  const data = await response.json();
  progressBar.value = data.progress ?? 0;
  statusText.textContent = data.message || data.status;

  if (data.status === 'completed' && data.download_url) {
    downloadLink.href = data.download_url;
    downloadLink.classList.remove('hidden');
  } else if (data.status === 'failed') {
    statusText.textContent = `任务失败: ${data.error}`;
  } else {
    setTimeout(() => pollProgress(jobId), 1500);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  formData.set('roles', JSON.stringify(serializeRoles()));
  formData.set('use_mock', form.querySelector('input[name="use_mock"]').checked ? 'true' : 'false');

  progressSection.classList.remove('hidden');
  progressBar.value = 0;
  downloadLink.classList.add('hidden');
  statusText.textContent = '任务已提交，正在排队...';

  const response = await fetch('/generate', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json();
    statusText.textContent = error.detail || '生成失败';
    return;
  }

  const { job_id: jobId } = await response.json();
  statusText.textContent = '正在生成音频...';
  pollProgress(jobId);
});
