"""GigaAM transcription service: upload video/audio -> text + SRT."""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .engine import Engine, Job, job_srt, job_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("giga-transcribe")

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

app = FastAPI(title="giga-transcribe")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

jobs: dict[str, Job] = {}
engine: Engine | None = None


def get_engine() -> Engine:
    global engine
    if engine is None:
        engine = Engine()  # loads GigaAM once, warm for all jobs
    return engine


def job_info(j: Job) -> dict:
    pct = round(j.done_sec / j.total_sec * 100) if j.total_sec else 0
    return {"id": j.id, "filename": j.filename, "status": j.status,
            "progress": pct, "phrases": len(j.phrases), "error": j.error}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/upload")
def upload(f: UploadFile):
    ext = Path(f.filename or "audio").suffix.lower()
    if ext not in {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mkv", ".webm", ".mov", ".avi"}:
        raise HTTPException(400, f"unsupported format: {ext or '?'}")
    jid = uuid.uuid4().hex[:8]
    dest = DATA / f"{jid}{ext}"
    dest.write_bytes(f.file.read())
    job = Job(id=jid, filename=f.filename or dest.name)
    jobs[jid] = job
    threading.Thread(target=lambda: get_engine().run_job(job, str(dest)),
                     daemon=True).start()
    return job_info(job)


@app.get("/jobs")
def list_jobs():
    return [job_info(j) for j in jobs.values()]


@app.get("/jobs/{jid}")
def job_status(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    info = job_info(j)
    info["preview"] = job_text(j)[-2000:]
    return info


@app.get("/jobs/{jid}/text", response_class=PlainTextResponse)
def job_txt(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return job_text(j)


@app.get("/jobs/{jid}/srt", response_class=PlainTextResponse)
def job_srt_dl(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return job_srt(j)
