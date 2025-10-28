"""Voice provider interfaces used for synthesizing speech."""

from __future__ import annotations

import base64
import io
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

        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        # 将角色配置拼装成 JSON 请求体提交给外部 TTS 服务
        response = requests.post(
            self._config.base_url.rstrip("/") + "/synthesize",
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
            # 某些服务会返回 base64 编码的音频
            body = response.json()
            audio_payload = body.get("audio")
            if not isinstance(audio_payload, str):
                raise RuntimeError("Voice provider JSON response did not contain 'audio' field.")
            return base64.b64decode(audio_payload)

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
