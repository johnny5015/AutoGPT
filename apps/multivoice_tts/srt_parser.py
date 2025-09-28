"""Utilities for parsing SRT subtitle files."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Iterable, List

from .models import SubtitleSegment

# Regular expression that matches an SRT timestamp line.
_TIMESTAMP_PATTERN = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def _parse_timestamp(value: str) -> timedelta:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return timedelta(
        hours=int(hours),
        minutes=int(minutes),
        seconds=int(seconds),
        milliseconds=int(millis),
    )


def parse_srt(content: str) -> List[SubtitleSegment]:
    """Parse the content of an SRT file into subtitle segments.

    The parser accepts a standard SRT structure and also infers speaker names
    when the caption text starts with the ``Speaker:`` convention. The
    remaining text is considered dialog.
    """

    segments: List[SubtitleSegment] = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        try:
            index = int(lines[0])
        except ValueError:
            # Skip malformed blocks that do not start with an index number.
            continue

        match = _TIMESTAMP_PATTERN.match(lines[1])
        if not match:
            continue

        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        text_lines = lines[2:]

        speaker = "Narrator"
        if text_lines:
            first_line = text_lines[0]
            if ":" in first_line:
                potential_speaker, remainder = first_line.split(":", 1)
                if remainder.strip():
                    speaker = potential_speaker.strip()
                    text_lines[0] = remainder.strip()

        text = " ".join(text_lines).strip()
        segments.append(SubtitleSegment(index=index, start=start, end=end, speaker=speaker, text=text))

    return segments


def iter_segments_from_file(path: str) -> Iterable[SubtitleSegment]:
    """Yield subtitle segments from a file on disk."""

    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    for segment in parse_srt(content):
        yield segment
