# 多角色字幕语音合成服务

该服务提供一个简单的 Web 界面，可上传包含角色台词的 `.srt` 字幕文件或音频文件：

- 支持调用第三方语音识别接口，将音频转写为带有情绪、语气与性别标签的字幕文件；
- 可为不同角色配置语音合成参数，并按时间轴拼接为可下载的 MP3 文件。

非常适合播客制作、视频配音或教学场景。

## 功能概述

- **音频转写**：上传 MP3/WAV 音频，通过第三方语音识别接口生成带情绪、语气、性别标注的字幕，并自动存档。
- **SRT 解析**：自动识别字幕中的时间轴以及 `角色|emotion=开心|tone=温柔|gender=female: 对白` 这类富文本格式。
- **多角色语音生成**：为每个角色配置不同的第三方语音合成参数；支持按角色或按性别匹配合成设置，未配置时使用内置的本地占位音频生成器。
- **时间线拼接**：将单句语音片段按照字幕时间码对齐并合成完整音频。
- **任务进度**：前端轮询后端任务状态，显示生成进度、状态说明与下载链接。
- **字幕管理**：历史字幕文件可在线查看、下载，并一键重新触发语音合成。

## 目录结构

```text
apps/srt_voice_service/
├── app.py                 # FastAPI 入口
├── services/
│   ├── audio_stitcher.py  # 音频拼接工具
│   ├── config.py          # 角色及服务端配置模型
│   ├── srt_parser.py      # 字幕解析逻辑
│   ├── speech_recognizer.py # 语音识别接口调用与占位实现
│   └── voice_provider.py  # 第三方接口调用与本地占位实现
├── static/
│   └── app.js             # 前端交互脚本
└── templates/
    └── index.html         # Web UI
```

生成的 MP3 文件默认保存在 `apps/srt_voice_service/generated/` 目录中；识别得到的字幕文件及其元数据会存放在 `apps/srt_voice_service/transcripts/` 目录。

## 运行步骤

1. 安装依赖（确保已安装 `ffmpeg` 以便导出 MP3）。项目在 `apps/srt_voice_service/requirements.txt`
   中列出了最小依赖列表，可使用 [uv](https://github.com/astral-sh/uv) 创建隔离环境：

   ```bash
   uv venv
   source .venv/bin/activate  # Windows 请使用 .venv\Scripts\activate
   uv pip install -r apps/srt_voice_service/requirements.txt
   ```

2. 启动服务（仍保持激活的虚拟环境）：

   ```bash
   uv run uvicorn apps.srt_voice_service.app:app --reload
   ```

3. 访问 `http://127.0.0.1:8000`，按步骤上传音频生成字幕或直接上传 SRT，随后配置角色参数触发语音合成。

## 配置说明

- **provider.base_url**：第三方语音合成接口的基础 URL，服务会在其后追加 `/synthesize` 路径。
- **provider.api_key**：若接口需要鉴权，服务会以 `Bearer` 方式写入 `Authorization` 请求头。
- **roles**：以角色名为键，配置 `voice_id`、语速、音调及可选的 `gender` 字段，其余字段会透传给第三方接口。
- **gender_roles**：按性别（`female` / `male` 等自定义标签）定义默认语音，当字幕中出现匹配的性别标签且未显式配置同名角色时将自动应用。

示例：

```json
{
  "provider": {
    "base_url": "https://api.example.com/tts",
    "api_key": "YOUR_TOKEN"
  },
  "roles": {
    "Alice": { "voice_id": "voice_a", "gender": "female", "speaking_rate": 1.05 },
    "Bob": { "voice_id": "voice_b", "gender": "male", "pitch": -1.5 }
  },
  "gender_roles": {
    "female": { "voice_id": "generic_female" },
    "male": { "voice_id": "generic_male" }
  }
}
```

当未提供 `provider.base_url` 时，后端会使用 `MockVoiceProvider` 生成占位音频，便于快速预览时间轴与拼接效果。

若语音识别配置中未指定第三方接口，同样会使用内置的 `MockSpeechRecognizer` 返回示例字幕，便于端到端联调。

## 注意事项

- SRT 台词需采用 `角色名: 内容` 的格式才能正确识别说话人。
- 第三方接口返回的内容可以是 MP3 等音频二进制流，或包含 Base64 字段的 JSON 数据。
- 若使用自定义音频格式，务必在角色配置中通过 `audio_format` 指定对应的格式，以便正确解析。

