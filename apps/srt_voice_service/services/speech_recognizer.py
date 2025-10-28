"""Speech recognition service abstractions."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List

import requests
import srt

from .config import ProviderConfig


@dataclass(slots=True)
class RecognizedSegment:
    """Represents a single transcription result from the recognizer."""

    speaker: str
    text: str
    start: timedelta
    end: timedelta
    emotion: str | None = None
    tone: str | None = None
    gender: str | None = None


class SpeechRecognizer:
    """Abstract base class for audio transcription providers."""

    def transcribe(self, audio_bytes: bytes, filename: str) -> List[RecognizedSegment]:
        raise NotImplementedError


class ThirdPartySpeechRecognizer(SpeechRecognizer):
    """Calls an external HTTP API to transcribe audio."""

    def __init__(self, config: ProviderConfig) -> None:
        self._config = config

    def transcribe(self, audio_bytes: bytes, filename: str) -> List[RecognizedSegment]:
        """将音频文件上传至第三方接口，并解析返回的带情感信息的字幕片段。"""

        # 使用 multipart/form-data 上传音频文件，保持与常见语音识别 API 的兼容性
        files = {"file": (filename, io.BytesIO(audio_bytes), "audio/mpeg")}
        headers = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        response = requests.post(
            self._config.base_url.rstrip("/") + "/transcribe",
            files=files,
            headers=headers,
            timeout=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Speech recognizer returned HTTP {response.status_code}: {response.text}"
            )

        # 接口约定返回 JSON，其中 segments 字段包含识别到的每个语音片段
        payload = response.json()
        segments_payload = payload.get("segments")
        if not isinstance(segments_payload, list):
            raise RuntimeError("Recognizer response did not include a 'segments' list.")

        segments: List[RecognizedSegment] = []
        for entry in segments_payload:
            if not isinstance(entry, dict):
                continue
            start_seconds = float(entry.get("start", 0))
            end_seconds = float(entry.get("end", start_seconds))
            segments.append(
                RecognizedSegment(
                    speaker=str(entry.get("speaker", "Narrator")),
                    text=str(entry.get("text", "")).strip(),
                    start=timedelta(seconds=start_seconds),
                    end=timedelta(seconds=end_seconds),
                    emotion=(str(entry.get("emotion")).strip() or None)
                    if entry.get("emotion")
                    else None,
                    tone=(str(entry.get("tone")).strip() or None)
                    if entry.get("tone")
                    else None,
                    gender=(str(entry.get("gender")).strip() or None)
                    if entry.get("gender")
                    else None,
                )
            )
        return segments


class MockSpeechRecognizer(SpeechRecognizer):
    """Generates a deterministic transcription for development environments."""

    def transcribe(self, audio_bytes: bytes, filename: str) -> List[RecognizedSegment]:  # noqa: ARG002
        """根据音频大小生成两段固定的示例字幕，便于本地调试。"""

        base_duration = max(len(audio_bytes) / 32000, 6.0)
        half = base_duration / 2
        return [
            RecognizedSegment(
                speaker="Alice",
                text="大家好，欢迎收听今天的节目！",
                start=timedelta(seconds=0),
                end=timedelta(seconds=half * 0.8),
                emotion="happy",
                tone="warm",
                gender="female",
            ),
            RecognizedSegment(
                speaker="Bob",
                text="我是联合主持人，我们将讨论语音合成的新功能。",
                start=timedelta(seconds=half * 0.8),
                end=timedelta(seconds=base_duration),
                emotion="excited",
                tone="energetic",
                gender="male",
            ),
        ]


def segments_to_srt(segments: Iterable[RecognizedSegment]) -> str:
    """Compose recognised segments into an SRT string with metadata tags."""

    # 在字幕行中追加 emotion/tone/gender 标签，方便后续语音合成时读取
    subtitles = []
    for index, segment in enumerate(segments, start=1):
        metadata_parts = []
        if segment.emotion:
            metadata_parts.append(f"emotion={segment.emotion}")
        if segment.tone:
            metadata_parts.append(f"tone={segment.tone}")
        if segment.gender:
            metadata_parts.append(f"gender={segment.gender}")
        speaker = segment.speaker or "Narrator"
        if metadata_parts:
            speaker = "|".join([speaker] + metadata_parts)
        content = f"{speaker}: {segment.text}"
        subtitles.append(
            srt.Subtitle(
                index=index,
                start=segment.start,
                end=segment.end,
                content=content,
            )
        )
    return srt.compose(subtitles)


def serialize_segments(segments: Iterable[RecognizedSegment]) -> list[dict[str, object]]:
    """Serialize transcription segments into JSON serialisable dictionaries."""

    # 结果会写入磁盘，供二次生成语音或在前端展示
    serialised: list[dict[str, object]] = []
    for segment in segments:
        serialised.append(
            {
                "speaker": segment.speaker,
                "text": segment.text,
                "start": segment.start.total_seconds(),
                "end": segment.end.total_seconds(),
                "emotion": segment.emotion,
                "tone": segment.tone,
                "gender": segment.gender,
            }
        )
    return serialised

