"""Integration helpers for invoking a third-party TTS provider."""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import requests
from pydub.generators import Sine

from .models import TTSRequest, TTSResponse

LOGGER = logging.getLogger(__name__)


@dataclass
class TTSSettings:
    """Configuration for the TTS client."""

    api_url: str
    api_key: Optional[str] = None
    use_mock: bool = False


class TTSClient:
    """Client responsible for communicating with a TTS provider."""

    def __init__(self, settings: TTSSettings) -> None:
        self.settings = settings

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Generate speech audio for the given text."""

        if self.settings.use_mock:
            return self._mock_tts(request)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        payload = {
            "voice_id": request.voice_id,
            "text": request.text,
            "speaker": request.speaker,
        }

        response = requests.post(self.settings.api_url, json=payload, timeout=60, headers=headers)
        response.raise_for_status()

        data = response.json()
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            raise ValueError("TTS provider response did not include 'audio_base64'.")

        audio_bytes = base64.b64decode(audio_base64)
        return TTSResponse(audio_bytes=audio_bytes)

    def _mock_tts(self, request: TTSRequest) -> TTSResponse:
        """Generate placeholder audio locally for development/testing."""

        duration_ms = max(500, len(request.text.split()) * 300)
        pitch = 440 + (hash(request.voice_id) % 200)
        sine_wave = Sine(pitch).to_audio_segment(duration=duration_ms).apply_gain(-10)
        buffer = io.BytesIO()
        sine_wave.export(buffer, format="mp3")
        return TTSResponse(audio_bytes=buffer.getvalue())
