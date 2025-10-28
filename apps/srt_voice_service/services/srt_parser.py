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
    emotion: str | None = None
    tone: str | None = None
    gender: str | None = None


def _split_speaker_and_text(payload: str) -> tuple[str, str, dict[str, str]]:
    """从字幕文本中拆分出说话人、正文以及 emotion/tone 等标记。"""

    if ":" in payload:
        potential_speaker, remainder = payload.split(":", 1)
        speaker_token = potential_speaker.strip()
        metadata: dict[str, str] = {}

        if "|" in speaker_token:
            # 约定格式：Speaker|emotion=happy|tone=warm: actual text
            parts = [part.strip() for part in speaker_token.split("|") if part.strip()]
            if parts:
                speaker = parts[0]
                for meta_part in parts[1:]:
                    if "=" not in meta_part:
                        continue
                    key, value = meta_part.split("=", 1)
                    metadata[key.strip().lower()] = value.strip()
            else:
                speaker = "Narrator"
        else:
            speaker = speaker_token

        if not speaker:
            speaker = "Narrator"
        return speaker, remainder.strip(), metadata
    return "Narrator", payload.strip(), {}


def parse_srt(raw_content: str) -> Iterator[SubtitleSegment]:
    """Yield subtitle segments from raw SRT content."""

    # 借助 python-srt 解析时间戳，再用自定义格式提取说话人和情感信息
    for entry in srt.parse(raw_content):
        text = entry.content.strip()
        if not text:
            continue
        speaker, content, metadata = _split_speaker_and_text(text)
        yield SubtitleSegment(
            speaker=speaker,
            text=content,
            start=entry.start,
            end=entry.end,
            emotion=metadata.get("emotion"),
            tone=metadata.get("tone"),
            gender=metadata.get("gender"),
        )
