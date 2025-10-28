"""Voice provider interfaces used for synthesizing speech."""

from __future__ import annotations

import base64
import io
import time
from abc import ABC, abstractmethod
from typing import Dict

import requests
from pydub.generators import Sine

from .config import ProviderConfig, RoleConfig


class VoiceProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    def synthesize(self, text: str, role: RoleConfig) -> bytes:
        """Generate audio bytes for the supplied text."""


class ThirdPartyVoiceProvider(VoiceProvider):
    """Calls an external HTTP API to synthesize speech."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def _build_headers(self, *, json_payload: bool = False) -> Dict[str, str]:
        """构建带鉴权信息的请求头，重复使用避免拼写错误。"""

        headers: Dict[str, str] = {}
        if json_payload:
            headers["Content-Type"] = "application/json"
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def synthesize(self, text: str, role: RoleConfig) -> bytes:
        """调用第三方接口完成文本到语音的转换。"""

        payload: Dict[str, object] = {
            "voice_id": role.voice_id,
            "text": text,
            "speaking_rate": role.speaking_rate,
            "pitch": role.pitch,
        }
        if role.gender:
            payload["gender"] = role.gender
        payload.update(role.extra)

        headers = self._build_headers(json_payload=True)
        start_url = self._config.base_url.rstrip("/") + "/synthesize"

        # 先提交异步任务请求，第三方服务通常会返回任务标识或立即返回音频内容
        response = requests.post(
            start_url,
            json=payload,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Voice provider returned HTTP {response.status_code}: {response.text}"
            )

        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            body = response.json()
            # 若服务直接返回音频（base64 或 URL），优先处理快速路径
            if "audio" in body:
                audio_payload = body.get("audio")
                if not isinstance(audio_payload, str):
                    raise RuntimeError(
                        "Voice provider JSON response did not contain a valid 'audio' field."
                    )
                return base64.b64decode(audio_payload)
            if "audio_url" in body:
                audio_url = str(body["audio_url"])
                return self._download_audio(audio_url)
            job_identifier = body.get("job_id") or body.get("id") or body.get("task_id")
            if not job_identifier:
                raise RuntimeError(
                    "Voice provider response missing both audio payload and job identifier."
                )
            return self._poll_for_completion(str(job_identifier))

        # 非 JSON 响应时视为直接返回音频内容（如流式 mp3）
        return response.content

    def _poll_for_completion(self, job_id: str) -> bytes:
        """轮询第三方任务状态，等待音频生成完成。"""

        status_url = self._config.base_url.rstrip("/") + f"/synthesize/{job_id}"
        deadline = time.monotonic() + self._config.poll_timeout_seconds
        headers = self._build_headers()

        while time.monotonic() < deadline:
            response = requests.get(
                status_url,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Voice provider status check failed with HTTP {response.status_code}: {response.text}"
                )

            if response.headers.get("Content-Type", "").startswith("application/json"):
                body: Dict[str, object] = response.json()
            else:
                raise RuntimeError("Voice provider status endpoint must return JSON data.")

            status = str(body.get("status") or body.get("state") or "").strip().lower()
            if status in {"completed", "succeeded", "ready", "success", "done"}:
                if "audio" in body:
                    audio_payload = body.get("audio")
                    if isinstance(audio_payload, str):
                        return base64.b64decode(audio_payload)
                    raise RuntimeError("Voice provider completed but returned invalid 'audio' content.")
                if "audio_url" in body:
                    return self._download_audio(str(body["audio_url"]))
                raise RuntimeError("Voice provider completed without providing an audio payload.")

            if status in {"failed", "error", "cancelled"}:
                message = body.get("message") or body.get("error") or "unknown error"
                raise RuntimeError(f"Voice provider reported job failure: {message}")

            # 状态仍在排队或运行中，等待一段时间再重试
            time.sleep(self._config.poll_interval_seconds)

        raise TimeoutError("Timed out waiting for voice provider job to complete.")

    def _download_audio(self, url: str) -> bytes:
        """从第三方提供的下载地址获取音频数据。"""

        headers = self._build_headers()
        response = requests.get(
            url,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Voice provider download failed with HTTP {response.status_code}: {response.text}"
            )
        return response.content


class MockVoiceProvider(VoiceProvider):
    """Generates placeholder audio tones for development environments."""

    def synthesize(self, text: str, role: RoleConfig) -> bytes:
        """生成不同频率的纯音，模拟语音输出，方便前端联调。"""

        words = max(len(text.split()), 1)
        duration_ms = max(350, words * 320)
        frequency = 300 + (abs(hash(role.voice_id)) % 300)
        segment = (
            Sine(frequency)
            .to_audio_segment(duration=duration_ms)
            .fade_in(40)
            .fade_out(80)
        )
        buffer = io.BytesIO()
        export_format = role.audio_format or "mp3"
        segment.export(buffer, format=export_format)
        return buffer.getvalue()
