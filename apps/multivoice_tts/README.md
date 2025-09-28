# 多角色语音生成服务

该 FastAPI 应用允许上传 SRT 字幕文件，调用第三方 TTS 接口按角色生成语音片段，并按时间线拼接成可下载的 MP3 文件。界面支持角色配置、生成进度展示以及任务完成后的文件下载。

## 功能概述

- 上传 SRT 字幕文件，支持通过 `角色: 台词` 结构识别说话人。
- 配置角色与第三方 TTS 接口的语音 ID 映射。
- 后台任务顺序请求 TTS 接口并合成完整的 MP3。
- 前端展示实时进度并提供下载链接。
- 提供模拟音色模式，方便在未配置第三方接口时演示。

## 运行方式

```bash
poetry install
poetry run uvicorn apps.multivoice_tts.main:app --reload
```

启动后访问 <http://localhost:8000> 即可使用界面。

## 第三方 TTS 接口说明

服务默认假设第三方接口返回如下结构：

```json
{
  "audio_base64": "..."  // base64 编码的 MP3 音频数据
}
```

请求体示例：

```json
{
  "voice_id": "voice_host",
  "text": "大家好，欢迎收听播客。",
  "speaker": "主持人"
}
```

可根据实际情况在 `TTSClient` 中调整请求参数或响应解析逻辑。
