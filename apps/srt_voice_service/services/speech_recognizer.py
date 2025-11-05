"""Speech recognition service abstractions."""

from __future__ import annotations

import io
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List, Mapping, Sequence

import requests
import srt

from .config import RecognizerProviderConfig


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

    def transcribe(
        self,
        *,
        audio_bytes: bytes | None,
        filename: str,
        audio_url: str | None = None,
    ) -> List[RecognizedSegment]:
        raise NotImplementedError


class ThirdPartySpeechRecognizer(SpeechRecognizer):
    """Calls an external HTTP API to transcribe audio."""

    def __init__(self, config: RecognizerProviderConfig) -> None:
        self._config = config

    def transcribe(
        self,
        *,
        audio_bytes: bytes | None,
        filename: str,
        audio_url: str | None = None,
    ) -> List[RecognizedSegment]:
        """将音频上传或提交 URL 给第三方接口，并解析返回的带情感信息字幕片段。"""

        if not audio_bytes and not audio_url:
            raise RuntimeError("Third-party recognizer requires audio bytes or a URL.")

        request_id = str(uuid.uuid4())
        # 统一组装鉴权请求头，便于提交和轮询使用
        headers = self._build_headers(request_id=request_id, json_payload=audio_bytes is None)

        start_url = self._config.base_url.rstrip("/") + self._config.start_path
        files = None
        data_payload = None

        if audio_bytes is not None:
            # 使用 multipart/form-data 上传音频文件，保持与常见语音识别 API 的兼容性
            files = {
                "file": (
                    filename,
                    io.BytesIO(audio_bytes),
                    "audio/mpeg",
                )
            }
        else:
            data_payload = {
                "audio_url": audio_url,
                "filename": filename,
            }

        request_kwargs: dict[str, object] = {
            "headers": headers,
            "timeout": self._config.timeout_seconds,
        }
        if files is not None:
            request_kwargs["files"] = files
        elif data_payload is not None:
            request_kwargs["json"] = data_payload

        response = requests.post(start_url, **request_kwargs)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Speech recognizer returned HTTP {response.status_code}: {response.text}"
            )

        self._ensure_submit_success(response)

        # 服务端异步生成识别结果，需要轮询状态接口，直到成功返回 JSON 结果
        result_payload = self._poll_for_result(request_id)
        return self._parse_segments(result_payload)

    def _build_headers(
        self,
        *,
        request_id: str,
        json_payload: bool = False,
    ) -> dict[str, str]:
        """统一构建第三方接口所需的请求头。"""

        headers: dict[str, str] = {
            "appId": self._config.app_id,
            "accessKey": self._config.access_key,
            "requestId": request_id,
        }
        if json_payload:
            headers["Content-Type"] = "application/json"
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        if self._config.extra_headers:
            headers.update(self._config.extra_headers)
        return headers

    def _ensure_submit_success(self, response: requests.Response) -> None:
        """根据响应头的状态码与消息判断任务是否提交成功。"""

        status_header = self._config.status_header.lower()
        message_header = self._config.message_header.lower()

        status_value = None
        message_value = None
        for key, value in response.headers.items():
            lowered = key.lower()
            if lowered == status_header:
                status_value = str(value)
            elif lowered == message_header:
                message_value = str(value)

        if status_value is None:
            # 若第三方未在响应头返回状态码，视为成功，以兼容旧接口
            return

        normalized = status_value.strip().lower()
        if normalized in {"0", "ok", "success", "succeeded", "200"}:
            return

        message = message_value or response.text or "recognizer reported failure"
        raise RuntimeError(f"Speech recognizer submission failed: {message}")

    def _poll_for_result(self, request_id: str) -> Mapping[str, object]:
        """轮询第三方识别结果，直到任务完成或超时。"""

        result_url = self._config.base_url.rstrip("/") + self._config.result_path
        deadline = time.monotonic() + self._config.poll_timeout_seconds

        while time.monotonic() < deadline:
            response = requests.get(
                result_url,
                headers=self._build_headers(request_id=request_id),
                timeout=self._config.timeout_seconds,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Speech recognizer polling failed with HTTP {response.status_code}: {response.text}"
                )

            try:
                payload = response.json()
            except ValueError as exc:  # pragma: no cover - defensive
                raise RuntimeError("Recognizer status endpoint must return JSON data.") from exc

            status = str(payload.get("status") or payload.get("state") or "").strip().lower()
            if status in {"success", "succeeded", "completed", "done", "ok"}:
                return payload
            if status in {"failed", "error", "cancelled"}:
                message = payload.get("message") or payload.get("error") or "unknown error"
                raise RuntimeError(f"Speech recognizer reported failure: {message}")

            time.sleep(self._config.poll_interval_seconds)

        raise TimeoutError("Timed out waiting for recognizer to return results.")

    def _parse_segments(self, payload: Mapping[str, object]) -> List[RecognizedSegment]:
        """将第三方 JSON 结果转换为内部的字幕段列表。"""

        segments_field = payload.get("result")
        if isinstance(segments_field, Mapping):
            # 一些接口会使用 {"result": {"segments": [...]}} 的形式
            inner = segments_field.get("segments")
            if isinstance(inner, Sequence):
                segments_field = inner

        if not isinstance(segments_field, Sequence):
            raise RuntimeError("Recognizer response missing 'result' segments list.")

        segments: List[RecognizedSegment] = []
        for entry in segments_field:
            if not isinstance(entry, Mapping):
                continue
            text = str(entry.get("text", "")).strip()
            if not text:
                continue

            start_ms = _safe_float(entry.get("start_time"))
            end_ms = _safe_float(entry.get("end_time", start_ms))
            if start_ms is None or end_ms is None:
                start_ms = _safe_float(entry.get("start"))
                end_ms = _safe_float(entry.get("end", start_ms))
                if start_ms is not None:
                    start_ms *= 1000.0
                if end_ms is not None:
                    end_ms *= 1000.0

            segments.append(
                RecognizedSegment(
                    speaker=str(entry.get("speaker", "Narrator")),
                    text=text,
                    start=timedelta(milliseconds=start_ms or 0.0),
                    end=timedelta(milliseconds=end_ms or (start_ms or 0.0)),
                    emotion=_normalize_optional(entry.get("emotion")),
                    tone=_normalize_optional(entry.get("tone")),
                    gender=_normalize_optional(entry.get("gender")),
                )
            )
        return segments


class MockSpeechRecognizer(SpeechRecognizer):
    """Generates a deterministic transcription for development environments."""

    def transcribe(
        self,
        *,
        audio_bytes: bytes | None,
        filename: str,
        audio_url: str | None = None,
    ) -> List[RecognizedSegment]:  # noqa: ARG002
        """根据音频大小生成两段固定的示例字幕，便于本地调试。"""

        # 当传入 URL 而非本地文件时，使用一个固定时长，避免额外的网络请求
        payload_size = len(audio_bytes or b"")
        base_duration = max(payload_size / 32000, 6.0)
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


def _normalize_optional(value: object | None) -> str | None:
    """将可选字段标准化为去除空白的字符串。"""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: object | None) -> float | None:
    """尽最大努力将任意对象转换为浮点数。"""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
