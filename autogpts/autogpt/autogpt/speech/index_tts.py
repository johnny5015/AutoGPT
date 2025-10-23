"""Text-to-speech provider that integrates the `index-tts` project."""
from __future__ import annotations

import contextlib
import logging
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from playsound import playsound

from autogpt.core.configuration import SystemConfiguration, UserConfigurable
from autogpt.speech.base import VoiceBase

logger = logging.getLogger(__name__)


class IndexTTSConfig(SystemConfiguration):
    """Configuration options for the local index-tts server."""

    base_url: str = UserConfigurable(default="http://localhost:8080")
    endpoint: str = UserConfigurable(default="/api/tts")
    voice: Optional[str] = UserConfigurable(default=None)
    language: Optional[str] = UserConfigurable(default=None)
    audio_format: str = UserConfigurable(default="mp3")
    request_timeout: float = UserConfigurable(default=60.0)


class IndexTTSSpeech(VoiceBase):
    """Use an index-tts instance that is running locally to synthesise audio."""

    def _setup(self, config: Optional[IndexTTSConfig]) -> None:
        self.config = config or IndexTTSConfig()

    def _speech(self, text: str, _: int = 0) -> bool:
        """Send text to the local index-tts server and play the resulting audio."""

        base = self.config.base_url.rstrip("/") + "/"
        endpoint = self.config.endpoint.lstrip("/")
        url = urljoin(base, endpoint)
        payload: dict[str, str] = {"text": text}
        if self.config.voice:
            payload["voice"] = self.config.voice
        if self.config.language:
            payload["language"] = self.config.language
        if self.config.audio_format:
            payload["format"] = self.config.audio_format

        try:
            response = requests.post(url, json=payload, timeout=self.config.request_timeout)
        except requests.RequestException:
            logger.exception("Failed to reach the index-tts server at %s", url)
            return False

        if response.status_code != 200:
            logger.error(
                "index-tts returned a non-success status: %s - %s",
                response.status_code,
                response.text,
            )
            return False

        suffix = f".{self.config.audio_format}" if self.config.audio_format else ".mp3"
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
                temp_audio.write(response.content)
                temp_audio_path = Path(temp_audio.name)

            playsound(str(temp_audio_path), True)
        except Exception:  # noqa: BLE001 - playsound can raise different platform specific errors
            logger.exception("Unable to play audio returned by index-tts")
            return False
        finally:
            with contextlib.suppress(OSError):
                if "temp_audio_path" in locals() and temp_audio_path.exists():
                    temp_audio_path.unlink()

        return True
