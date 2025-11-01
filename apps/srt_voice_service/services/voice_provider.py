"""Voice provider interfaces used for synthesizing speech."""

from __future__ import annotations

import base64
import io
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict

import requests
from pydub import AudioSegment
from pydub.generators import Sine

from .config import RoleConfig, VoiceProviderConfig
from .srt_parser import SubtitleSegment


@dataclass(slots=True)
class SynthesizedAudio:
    """封装语音合成接口返回的音频内容与格式。"""

    data: bytes
    audio_format: str


class VoiceProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    def synthesize(self, segment: SubtitleSegment, role: RoleConfig) -> SynthesizedAudio:
        """Generate audio bytes for the supplied subtitle segment."""


class ThirdPartyVoiceProvider(VoiceProvider):
    """Calls an external HTTP API to synthesize speech."""

    def __init__(self, config: VoiceProviderConfig) -> None:
        self._config = config

    def _build_headers(self, *, json_payload: bool = False) -> Dict[str, str]:
        """构建带鉴权信息的请求头，重复使用避免拼写错误。"""

        headers: Dict[str, str] = {}
        if json_payload:
            headers["Content-Type"] = "application/json"
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return headers

    def synthesize(self, segment: SubtitleSegment, role: RoleConfig) -> SynthesizedAudio:
        """调用第三方接口完成文本到语音的转换。"""

        payload: Dict[str, object] = {
            "voice_id": role.voice_id,
            "text": segment.text,
            "speaking_rate": role.speaking_rate,
            "pitch": role.pitch,
        }
        reference_audio = role.reference_audio_path
        if reference_audio:
            payload["reference_audio_path"] = reference_audio

        # emotion/tone 优先使用字幕中携带的标记，其次使用角色默认值
        emotion = segment.emotion or role.default_emotion
        tone = segment.tone or role.default_tone
        gender = segment.gender or role.gender
        if gender:
            payload["gender"] = gender
        if emotion:
            payload["emotion"] = emotion
        if tone:
            payload["tone"] = tone
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
                return self._normalize_audio_format(
                    base64.b64decode(audio_payload), role.audio_format
                )
            if "audio_url" in body:
                audio_url = str(body["audio_url"])
                audio_bytes, detected_format = self._download_audio(audio_url)
                return self._normalize_audio_format(
                    audio_bytes,
                    role.audio_format,
                    detected_format=detected_format,
                )
            job_identifier = body.get("job_id") or body.get("id") or body.get("task_id")
            if not job_identifier:
                raise RuntimeError(
                    "Voice provider response missing both audio payload and job identifier."
                )
            audio_bytes, detected_format = self._poll_for_completion(str(job_identifier))
            return self._normalize_audio_format(
                audio_bytes,
                role.audio_format,
                detected_format=detected_format,
            )

        # 非 JSON 响应时视为直接返回音频内容（如流式 mp3）
        return self._normalize_audio_format(
            response.content,
            role.audio_format,
            detected_format=response.headers.get("Content-Type"),
        )

    def _poll_for_completion(self, job_id: str) -> tuple[bytes, str | None]:
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
                        return base64.b64decode(audio_payload), body.get("audio_format")
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

    def _download_audio(self, url: str) -> tuple[bytes, str | None]:
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
        return response.content, response.headers.get("Content-Type")

    def _normalize_audio_format(
        self,
        audio_bytes: bytes,
        requested_format: str | None,
        *,
        detected_format: str | None = None,
    ) -> SynthesizedAudio:
        """确保音频以 mp3 返回，若第三方提供 wav 则自动转换。"""

        # 首选第三方返回的格式描述，其次使用角色配置的格式
        format_hint = None
        if detected_format:
            format_hint = detected_format.split("/")[-1].strip().lower()
        normalized_requested = (requested_format or "mp3").strip().lower()
        current_format = (format_hint or normalized_requested or "mp3").lower()
        format_aliases = {"mpeg": "mp3", "x-wav": "wav", "wave": "wav"}
        current_format = format_aliases.get(current_format, current_format)
        is_wav_payload = audio_bytes[:4] == b"RIFF"

        if current_format == "wav" or is_wav_payload:
            # 当第三方只返回 wav 时，将其转码为 mp3，再交给混音环节
            buffer = io.BytesIO(audio_bytes)
            segment = AudioSegment.from_file(buffer, format="wav")
            mp3_buffer = io.BytesIO()
            segment.export(mp3_buffer, format="mp3")
            return SynthesizedAudio(data=mp3_buffer.getvalue(), audio_format="mp3")

        return SynthesizedAudio(data=audio_bytes, audio_format=current_format)


class MockVoiceProvider(VoiceProvider):
    """Generates placeholder audio tones for development environments."""

    def synthesize(self, segment: SubtitleSegment, role: RoleConfig) -> SynthesizedAudio:
        """生成不同频率的纯音，模拟语音输出，方便前端联调。"""

        words = max(len(segment.text.split()), 1)
        duration_ms = max(350, words * 320)
        frequency = 300 + (abs(hash(role.voice_id)) % 300)
        tone_segment = (
            Sine(frequency)
            .to_audio_segment(duration=duration_ms)
            .fade_in(40)
            .fade_out(80)
        )
        buffer = io.BytesIO()
        export_format = role.audio_format or "mp3"
        target_format = "mp3" if export_format.lower() == "wav" else export_format
        tone_segment.export(buffer, format=target_format)
        return SynthesizedAudio(data=buffer.getvalue(), audio_format=target_format)
