"""Tests for transcript save and archive workflow."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.srt_voice_service import app as service_app


@pytest.fixture()
def temp_storage(monkeypatch):
    """Provide isolated storage paths under APP_DIR and clean up after."""

    base = Path(tempfile.mkdtemp(dir=service_app.APP_DIR))
    transcripts_dir = base / "transcripts"
    generated_dir = base / "generated"
    archive_dir = transcripts_dir / "archive"

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(service_app, "TRANSCRIPTS_DIR", transcripts_dir)
    monkeypatch.setattr(service_app, "GENERATED_DIR", generated_dir)
    monkeypatch.setattr(service_app, "ARCHIVE_DIR", archive_dir)

    try:
        yield {
            "base": base,
            "transcripts": transcripts_dir,
            "generated": generated_dir,
            "archive": archive_dir,
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def client(temp_storage):
    """Create a TestClient for the FastAPI application."""

    return TestClient(service_app.app)


@pytest.fixture()
def sample_segments():
    """Return a small set of valid segment payloads."""

    return [
        {"speaker": "Alice", "text": "Hello", "start": 0, "end": 1.2},
        {"speaker": "Bob", "text": "World", "start": 1.2, "end": 2.5, "emotion": "happy"},
    ]


def test_save_transcript_creates_files(client, temp_storage, sample_segments):
    """Saving a transcript writes SRT and metadata to the configured directories."""

    payload = {"original_filename": "demo.srt", "segments": sample_segments}

    response = client.post("/transcripts/save", json=payload)
    assert response.status_code == 200

    body = response.json()
    transcript_id = body["transcript_id"]
    metadata = body["metadata"]

    srt_path = temp_storage["transcripts"] / f"{transcript_id}.srt"
    meta_path = temp_storage["transcripts"] / f"{transcript_id}.json"

    assert srt_path.exists()
    assert meta_path.exists()

    assert metadata["original_filename"] == "demo.srt"
    assert metadata["segment_count"] == 2
    assert metadata["download_url"].endswith(f"/transcripts/{transcript_id}/download")

    saved_srt = srt_path.read_text(encoding="utf-8")
    assert "Alice" in saved_srt
    assert "Bob" in saved_srt

    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta["segments"][0]["text"] == "Hello"


def test_save_transcript_archives_source(client, temp_storage, sample_segments):
    """Saving from an existing transcript archives the source copy."""

    # Seed a source transcript to archive
    source_id = "source-123"
    source_srt = temp_storage["transcripts"] / f"{source_id}.srt"
    source_meta = temp_storage["transcripts"] / f"{source_id}.json"
    source_srt.write_text("Demo source", encoding="utf-8")
    source_meta.write_text(json.dumps({"id": source_id, "segments": []}), encoding="utf-8")

    payload = {
        "original_filename": "edited.srt",
        "segments": sample_segments,
        "source_transcript_id": source_id,
    }

    response = client.post("/transcripts/save", json=payload)
    assert response.status_code == 200

    archived = list(temp_storage["archive"].glob(f"{source_id}/*.srt"))
    assert archived, "source transcript should be archived when saving an edit"
