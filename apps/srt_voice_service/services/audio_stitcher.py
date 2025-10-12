"""Utilities for combining voice segments into a single timeline."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List, Tuple

from pydub import AudioSegment

from .srt_parser import SubtitleSegment


@dataclass(slots=True)
class ExportedAudio:
    """Details about a rendered audio file."""

    path: Path
    duration_seconds: float


class AudioTimelineBuilder:
    """Accumulates subtitle-aligned audio segments and mixes them into a single file."""

    def __init__(self) -> None:
        self._entries: List[Tuple[SubtitleSegment, AudioSegment]] = []

    def add_segment(self, subtitle: SubtitleSegment, audio_bytes: bytes, audio_format: str) -> None:
        """Add an audio clip aligned with a subtitle segment."""

        if not audio_bytes:
            raise ValueError("Received empty audio payload from provider.")
        segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format=audio_format)
        self._entries.append((subtitle, segment))

    def export(self, output_path: Path) -> ExportedAudio:
        if not self._entries:
            raise ValueError("No audio segments were added to the timeline.")

        buffer = timedelta(seconds=1)
        total_duration = timedelta()
        for subtitle, segment in self._entries:
            subtitle_window = subtitle.end - subtitle.start
            segment_duration = timedelta(milliseconds=len(segment))
            effective_duration = max(subtitle_window, segment_duration)
            segment_end = subtitle.start + effective_duration
            if segment_end > total_duration:
                total_duration = segment_end

        total_ms = int((total_duration + buffer).total_seconds() * 1000)
        timeline = AudioSegment.silent(duration=total_ms)

        for subtitle, segment in self._entries:
            start_ms = int(subtitle.start.total_seconds() * 1000)
            timeline = timeline.overlay(segment, position=start_ms)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeline.export(output_path, format="mp3")
        return ExportedAudio(path=output_path, duration_seconds=timeline.duration_seconds)
