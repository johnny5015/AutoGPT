"""Data models for the multi-voice TTS service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SubtitleSegment:
    """Represents a single subtitle entry extracted from the SRT file."""

    index: int
    start: timedelta
    end: timedelta
    speaker: str
    text: str


@dataclass
class RoleConfig:
    """Mapping between a logical speaker name and a TTS voice identifier."""

    name: str
    voice_id: str


@dataclass
class GenerationJob:
    """Represents a background job that renders audio for a full subtitle file."""

    job_id: str
    output_path: Path
    segments: List[SubtitleSegment] = field(default_factory=list)
    status: str = "pending"
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None

    def update_progress(self, current: int, total: int) -> None:
        if total == 0:
            self.progress = 1.0
            return
        self.progress = max(0.0, min(1.0, current / total))


@dataclass
class TTSRequest:
    """Parameters forwarded to the TTS provider when requesting audio."""

    text: str
    voice_id: str
    speaker: str


@dataclass
class TTSResponse:
    """Container for audio bytes returned by the TTS provider."""

    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
