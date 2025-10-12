"""FastAPI application for generating multi-speaker voiceovers from SRT files."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .services.audio_stitcher import AudioTimelineBuilder
from .services.config import GenerationConfig
from .services.srt_parser import parse_srt
from .services.voice_provider import MockVoiceProvider, ThirdPartyVoiceProvider, VoiceProvider

APP_DIR = Path(__file__).resolve().parent
GENERATED_DIR = APP_DIR / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

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
            role_config = config.roles.get(subtitle.speaker)
            if not role_config:
                raise ValueError(
                    f"No voice configuration found for speaker '{subtitle.speaker}'. "
                    "Please add a mapping in the role configuration."
                )

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
