"""Utilities for assembling generated audio into a single MP3 file."""

from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from pydub import AudioSegment

from .models import SubtitleSegment, TTSResponse


def _timedelta_to_millis(value: timedelta) -> int:
    return int(value.total_seconds() * 1000)


def compose_audio(
    segments: Sequence[SubtitleSegment],
    responses: Sequence[TTSResponse],
    output_path: Path,
    gap_fill: bool = True,
) -> None:
    """Combine the generated audio clips to respect the subtitle timeline."""

    if len(segments) != len(responses):
        raise ValueError("Segments and responses must have identical lengths.")

    combined = AudioSegment.silent(duration=0)
    current_time_ms = 0

    for segment, response in zip(segments, responses):
        clip = AudioSegment.from_file(io.BytesIO(response.audio_bytes), format="mp3")
        start_ms = _timedelta_to_millis(segment.start)
        if gap_fill and start_ms > current_time_ms:
            combined += AudioSegment.silent(duration=start_ms - current_time_ms)
            current_time_ms = start_ms

        combined += clip
        current_time_ms += len(clip)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(output_path, format="mp3")
