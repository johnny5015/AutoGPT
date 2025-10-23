"""IndexTTS2 speech module."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

import requests
from playsound import playsound

from autogpt.core.configuration import SystemConfiguration, UserConfigurable

from .base import VoiceBase

logger = logging.getLogger(__name__)


class IndexTTS2Config(SystemConfiguration):
    """Configuration options for the IndexTTS2 provider."""

    api_key: Optional[str] = UserConfigurable(default=None)
    base_url: str = UserConfigurable(default="https://api.indextts.com/v2")
    voice: str = UserConfigurable(default="default")
    language: Optional[str] = UserConfigurable(default=None)
    audio_format: str = UserConfigurable(default="mp3")
    request_timeout: float = UserConfigurable(default=30.0)


class IndexTTS2Speech(VoiceBase):
    """Text-to-speech implementation backed by the IndexTTS2 API."""

    def _setup(self, config: IndexTTS2Config) -> None:
        self._config = config
        self._headers = {"Content-Type": "application/json"}
        if config.api_key:
            self._headers["Authorization"] = f"Bearer {config.api_key}"

    def _speech(self, text: str, voice_index: int = 0) -> bool:  # noqa: ARG002 - voice_index part of interface
        payload = {
            "text": text,
            "voice": self._config.voice,
            "format": self._config.audio_format,
        }
        if self._config.language:
            payload["language"] = self._config.language

        try:
            response = requests.post(
                f"{self._config.base_url.rstrip('/')}/synthesize",
                json=payload,
                headers=self._headers,
                timeout=self._config.request_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as err:
            logger.error("IndexTTS2 request failed: %s", err, exc_info=True)
            return False

        suffix = f".{self._config.audio_format}" if self._config.audio_format else ".mp3"
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        try:
            with open(path, "wb") as audio_file:
                audio_file.write(response.content)

            playsound(path, block=True)
            return True
        except Exception:
            logger.exception("Failed to play IndexTTS2 audio output")
            return False
        finally:
            try:
                os.remove(path)
            except OSError:
                logger.warning("Unable to remove temporary audio file: %s", path)
