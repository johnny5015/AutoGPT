"""FastAPI entry-point for the multi-voice TTS web service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .jobs import GenerationManager
from .models import RoleConfig
from .tts_service import TTSSettings

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

app = FastAPI(title="Multi-Voice TTS Service", description="Generate podcast-ready audio from SRT subtitles.")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
manager = GenerationManager(OUTPUT_DIR)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


def _parse_roles(roles_raw: str) -> List[RoleConfig]:
    try:
        payload = json.loads(roles_raw) if roles_raw else []
    except json.JSONDecodeError as error:  # noqa: FBT003 - propagate as validation error
        raise HTTPException(status_code=400, detail=f"角色配置格式错误: {error}") from error

    roles: List[RoleConfig] = []
    for entry in payload:
        name = entry.get("name")
        voice_id = entry.get("voice_id")
        if not name or not voice_id:
            raise HTTPException(status_code=400, detail="角色配置必须包含 name 和 voice_id 字段")
        roles.append(RoleConfig(name=name, voice_id=voice_id))
    return roles


@app.post("/generate", response_model=None)
async def generate_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    roles: str = Form("[]"),
    api_url: str = Form(""),
    api_key: str = Form(""),
    use_mock: bool = Form(False),
) -> JSONResponse:
    if not file.filename.endswith(".srt"):
        raise HTTPException(status_code=400, detail="仅支持 SRT 字幕文件")

    srt_content = (await file.read()).decode("utf-8")
    parsed_roles = _parse_roles(roles)

    if not api_url and not use_mock:
        raise HTTPException(status_code=400, detail="请提供 TTS 接口地址或启用模拟模式")

    job = manager.create_job(
        srt_content=srt_content,
        roles=parsed_roles,
        tts_settings=TTSSettings(api_url=api_url or "mock://tts", api_key=api_key or None, use_mock=use_mock),
        background_tasks=background_tasks,
    )

    return JSONResponse({"job_id": job.job_id})


@app.get("/progress/{job_id}")
async def get_progress(job_id: str) -> JSONResponse:
    job = await manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到任务")
    return JSONResponse({
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "download_url": f"/download/{job.job_id}" if job.status == "completed" else None,
    })


@app.get("/download/{job_id}")
async def download(job_id: str) -> FileResponse:
    job = await manager.get_job(job_id)
    if not job or job.status != "completed":
        raise HTTPException(status_code=404, detail="任务尚未完成或不存在")

    return FileResponse(
        path=job.output_path,
        filename=f"{job_id}.mp3",
        media_type="audio/mpeg",
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("apps.multivoice_tts.main:app", host="0.0.0.0", port=port, reload=False)
