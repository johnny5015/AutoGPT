"""Utilities for parsing SRT subtitle files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator

import srt


@dataclass(slots=True)
class SubtitleSegment:
    """Lightweight representation of a single SRT cue."""

    speaker: str
    text: str
    start: timedelta
    end: timedelta


def _split_speaker_and_text(payload: str) -> tuple[str, str]:
    if ":" in payload:
        potential_speaker, remainder = payload.split(":", 1)
        speaker = potential_speaker.strip()
        if speaker and speaker.replace(" ", "").isalpha():
            return speaker, remainder.strip()
    return "Narrator", payload.strip()


def parse_srt(raw_content: str) -> Iterator[SubtitleSegment]:
    """Yield subtitle segments from raw SRT content."""

    for entry in srt.parse(raw_content):
        text = entry.content.strip()
        if not text:
            continue
        speaker, content = _split_speaker_and_text(text)
        yield SubtitleSegment(
            speaker=speaker,
            text=content,
            start=entry.start,
            end=entry.end,
        )
