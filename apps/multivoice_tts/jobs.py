"""Background job manager for TTS rendering."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import BackgroundTasks

from .audio_composer import compose_audio
from .models import GenerationJob, RoleConfig, TTSRequest
from .srt_parser import parse_srt
from .tts_service import TTSClient, TTSSettings


@dataclass
class JobState:
    job: GenerationJob
    roles: Dict[str, RoleConfig]


class GenerationManager:
    """Coordinates long-running generation jobs."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self._jobs: Dict[str, JobState] = {}

    def create_job(
        self,
        srt_content: str,
        roles: List[RoleConfig],
        tts_settings: TTSSettings,
        background_tasks: BackgroundTasks,
    ) -> GenerationJob:
        job_id = uuid.uuid4().hex
        output_path = self.output_dir / f"{job_id}.mp3"
        segments = parse_srt(srt_content)

        job = GenerationJob(job_id=job_id, output_path=output_path, segments=segments)
        state = JobState(job=job, roles={role.name: role for role in roles})

        self._jobs[job_id] = state
        background_tasks.add_task(self._run_job, job_id, tts_settings)
        return job

    async def _run_job(self, job_id: str, tts_settings: TTSSettings) -> None:
        state = self._jobs[job_id]
        job = state.job
        job.status = "running"
        tts_client = TTSClient(tts_settings)

        responses = []
        total = len(job.segments)
        for idx, segment in enumerate(job.segments, start=1):
            role = state.roles.get(segment.speaker)
            voice_id = role.voice_id if role else segment.speaker
            request = TTSRequest(text=segment.text, voice_id=voice_id, speaker=segment.speaker)
            try:
                response = await asyncio.get_event_loop().run_in_executor(None, tts_client.synthesize, request)
            except Exception as error:  # noqa: BLE001 - propagate error info
                job.status = "failed"
                job.error = str(error)
                return

            responses.append(response)
            job.update_progress(idx, total)

        try:
            await asyncio.get_event_loop().run_in_executor(None, compose_audio, job.segments, responses, job.output_path)
        except Exception as error:  # noqa: BLE001 - propagate error info
            job.status = "failed"
            job.error = str(error)
            return

        job.status = "completed"
        job.progress = 1.0
        job.message = "音频生成完成"

    async def get_job(self, job_id: str) -> Optional[GenerationJob]:
        state = self._jobs.get(job_id)
        if not state:
            return None
        return state.job
