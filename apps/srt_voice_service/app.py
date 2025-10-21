"""FastAPI application for generating multi-speaker voiceovers from SRT files."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .services.audio_stitcher import AudioTimelineBuilder
from .services.config import GenerationConfig, ProviderConfig
from .services.speech_recognizer import (
    MockSpeechRecognizer,
    SpeechRecognizer,
    ThirdPartySpeechRecognizer,
    segments_to_srt,
    serialize_segments,
)
from .services.srt_parser import parse_srt
from .services.voice_provider import MockVoiceProvider, ThirdPartyVoiceProvider, VoiceProvider

APP_DIR = Path(__file__).resolve().parent
GENERATED_DIR = APP_DIR / "generated"
TRANSCRIPTS_DIR = APP_DIR / "transcripts"
SAFE_TRANSCRIPT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="SRT Voice Composer")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

_tasks_lock = threading.Lock()
_tasks: Dict[str, Dict[str, Any]] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main UI."""
    return templates.TemplateResponse("index.html", {"request": request})


def _load_generation_config(raw_config: str | None) -> GenerationConfig:
    if not raw_config:
        raise HTTPException(status_code=400, detail="Missing role configuration JSON.")

    try:
        parsed = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    return GenerationConfig.from_dict(parsed)


def _load_provider_config(payload: Mapping[str, object] | None) -> Optional[ProviderConfig]:
    if not payload:
        return None
    try:
        return ProviderConfig.from_mapping(payload)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_recognizer(raw_config: str | None) -> SpeechRecognizer:
    provider_config: Optional[ProviderConfig] = None
    if raw_config:
        try:
            parsed = json.loads(raw_config)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

        provider_payload = None
        if isinstance(parsed, Mapping):
            raw_provider = parsed.get("provider")
            if isinstance(raw_provider, Mapping):
                provider_payload = raw_provider
        provider_config = _load_provider_config(provider_payload)

    if provider_config:
        return ThirdPartySpeechRecognizer(provider_config)
    return MockSpeechRecognizer()


def _get_voice_provider(config: GenerationConfig) -> VoiceProvider:
    provider_conf = config.provider
    if provider_conf and provider_conf.base_url:
        return ThirdPartyVoiceProvider(provider_conf)
    return MockVoiceProvider()


def _update_task(job_id: str, **updates: Any) -> None:
    with _tasks_lock:
        task = _tasks.setdefault(job_id, {"status": "queued", "progress": 0.0})
        task.update(updates)


def _process_generation(job_id: str, srt_payload: bytes, config: GenerationConfig) -> None:
    try:
        _update_task(job_id, status="processing", progress=0.0, message="Parsing subtitles")
        subtitles = list(parse_srt(srt_payload.decode("utf-8")))
        if not subtitles:
            raise ValueError("The provided SRT file does not contain any dialogue entries.")

        provider = _get_voice_provider(config)
        total_segments = len(subtitles)
        timeline = AudioTimelineBuilder()

        for idx, subtitle in enumerate(subtitles, start=1):
            role_config = config.resolve_role(subtitle.speaker, subtitle.gender)

            _update_task(
                job_id,
                message=f"Synthesizing voice for {subtitle.speaker}",
                progress=round((idx - 1) / total_segments * 100, 2),
            )

            audio_bytes = provider.synthesize(subtitle.text, role_config)
            timeline.add_segment(subtitle, audio_bytes, role_config.audio_format)

        output_path = GENERATED_DIR / f"{job_id}.mp3"
        _update_task(job_id, message="Mixing audio tracks")
        exported = timeline.export(output_path)

        _update_task(
            job_id,
            status="completed",
            progress=100.0,
            message="Voiceover successfully generated",
            download_url=f"/download/{job_id}",
            duration_seconds=exported.duration_seconds,
        )
    except Exception as exc:  # pylint: disable=broad-except
        _update_task(job_id, status="failed", message=str(exc))


def _ensure_safe_transcript_path(transcript_id: str, extension: str) -> Path:
    if not SAFE_TRANSCRIPT_ID_PATTERN.fullmatch(transcript_id):
        raise HTTPException(status_code=400, detail="Invalid transcript identifier")

    transcripts_dir = TRANSCRIPTS_DIR.resolve()
    candidate_path = (TRANSCRIPTS_DIR / f"{transcript_id}.{extension}").resolve()
    try:
        candidate_path.relative_to(transcripts_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid transcript identifier") from exc

    return candidate_path


def _transcript_metadata_path(transcript_id: str) -> Path:
    return _ensure_safe_transcript_path(transcript_id, "json")


def _transcript_file_path(transcript_id: str) -> Path:
    return _ensure_safe_transcript_path(transcript_id, "srt")


def _save_transcript(
    transcript_id: str,
    original_filename: str,
    srt_text: str,
    segments: list[dict[str, object]],
) -> dict[str, Any]:
    srt_path = _transcript_file_path(transcript_id)
    metadata_path = _transcript_metadata_path(transcript_id)
    srt_path.write_text(srt_text, encoding="utf-8")

    duration = max((segment.get("end", 0.0) for segment in segments), default=0.0)
    speakers = sorted({str(segment.get("speaker", "Narrator")) for segment in segments})
    metadata = {
        "id": transcript_id,
        "original_filename": original_filename,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "segment_count": len(segments),
        "speakers": speakers,
        "duration_seconds": duration,
        "emotions": sorted({segment.get("emotion") for segment in segments if segment.get("emotion")}),
        "tones": sorted({segment.get("tone") for segment in segments if segment.get("tone")}),
        "srt_path": str(srt_path.relative_to(APP_DIR)),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _load_transcript_metadata(transcript_id: str) -> dict[str, Any]:
    metadata_path = _transcript_metadata_path(transcript_id)
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Transcript metadata not found")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _load_transcript_srt(transcript_id: str) -> str:
    srt_path = _transcript_file_path(transcript_id)
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="Transcript SRT file not found")
    return srt_path.read_text(encoding="utf-8")


def _list_transcripts() -> list[dict[str, Any]]:
    transcripts: list[dict[str, Any]] = []
    for metadata_file in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        transcripts.append(metadata)

    transcripts.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    for transcript in transcripts:
        transcript["download_url"] = f"/transcripts/{transcript['id']}/download"
    return transcripts


@app.post("/generate")
async def generate_voiceover(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    config: str = Form(...),
) -> JSONResponse:
    """Accept SRT + configuration and start the generation job."""
    srt_payload = await file.read()
    if not srt_payload:
        raise HTTPException(status_code=400, detail="Uploaded SRT file was empty.")

    job_id = str(uuid.uuid4())
    generation_config = _load_generation_config(config)

    with _tasks_lock:
        _tasks[job_id] = {"status": "queued", "progress": 0.0, "message": "Waiting to start"}

    background_tasks.add_task(_process_generation, job_id, srt_payload, generation_config)
    return JSONResponse({"job_id": job_id})


@app.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    config: Optional[str] = Form(None),
) -> JSONResponse:
    """Generate a metadata-rich subtitle file from an uploaded audio clip."""

    audio_payload = await file.read()
    if not audio_payload:
        raise HTTPException(status_code=400, detail="Uploaded音频文件为空。")

    recognizer = _load_recognizer(config)
    segments = recognizer.transcribe(audio_payload, file.filename or "audio.mp3")
    if not segments:
        raise HTTPException(status_code=400, detail="识别接口未返回有效的字幕片段。")

    srt_text = segments_to_srt(segments)
    transcript_id = str(uuid.uuid4())
    metadata = _save_transcript(
        transcript_id,
        file.filename or "audio.mp3",
        srt_text,
        serialize_segments(segments),
    )

    return JSONResponse(
        {
            "transcript_id": transcript_id,
            "download_url": f"/transcripts/{transcript_id}/download",
            "metadata": metadata,
            "srt": srt_text,
        }
    )


@app.get("/transcripts")
async def list_transcripts() -> JSONResponse:
    return JSONResponse({"transcripts": _list_transcripts()})


@app.get("/transcripts/{transcript_id}")
async def get_transcript(transcript_id: str) -> JSONResponse:
    metadata = _load_transcript_metadata(transcript_id)
    srt_text = _load_transcript_srt(transcript_id)
    metadata["download_url"] = f"/transcripts/{transcript_id}/download"
    metadata["srt"] = srt_text
    return JSONResponse(metadata)


@app.get("/transcripts/{transcript_id}/download")
async def download_transcript(transcript_id: str) -> FileResponse:
    srt_path = _transcript_file_path(transcript_id)
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")
    return FileResponse(
        srt_path,
        media_type="application/x-subrip",
        filename=f"transcript-{transcript_id}.srt",
    )


@app.post("/transcripts/{transcript_id}/generate")
async def generate_from_transcript(
    transcript_id: str,
    background_tasks: BackgroundTasks,
    config: str = Form(...),
) -> JSONResponse:
    srt_text = _load_transcript_srt(transcript_id)

    job_id = str(uuid.uuid4())
    generation_config = _load_generation_config(config)

    with _tasks_lock:
        _tasks[job_id] = {"status": "queued", "progress": 0.0, "message": "Waiting to start"}

    background_tasks.add_task(_process_generation, job_id, srt_text.encode("utf-8"), generation_config)
    return JSONResponse({"job_id": job_id})


@app.get("/status/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    with _tasks_lock:
        task = _tasks.get(job_id)
    if not task:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(task)


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    output_path = GENERATED_DIR / f"{job_id}.mp3"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Generated audio not found")
    return FileResponse(
        output_path,
        media_type="audio/mpeg",
        filename=f"voiceover-{job_id}.mp3",
    )


__all__ = ["app"]
