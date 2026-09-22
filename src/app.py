from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .engine import Engine, Job, job_srt, job_text, job_vtt
from .pipeline import run_url_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("giga-transcribe")

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mkv",
              ".webm", ".mov", ".avi", ".mpga", ".mpeg", ".oga", ".opus"}

app = FastAPI(title="giga-transcribe")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

jobs: dict[str, Job] = {}
engine: Engine | None = None


def get_engine() -> Engine:
    global engine
    if engine is None:
        engine = Engine()
    return engine


def job_info(j: Job) -> dict:
    pct = round(j.done_sec / j.total_sec * 100) if j.total_sec else 0
    return {"id": j.id, "filename": j.filename, "status": j.status,
            "stage": j.status,
            "progress": pct, "phrases": len(j.phrases), "error": j.error,
            "total_sec": round(j.total_sec, 1), "done_sec": round(j.done_sec, 1)}


def check_ext(filename: str) -> str:
    ext = Path(filename or "audio").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(400, f"unsupported format: {ext or '?'}")
    return ext


def save_upload(f: UploadFile) -> Path:
    ext = check_ext(f.filename or "")
    jid = uuid.uuid4().hex[:8]
    dest = DATA / f"{jid}{ext}"
    dest.write_bytes(f.file.read())
    return dest


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.post("/upload")
def upload(f: UploadFile):
    dest = save_upload(f)
    jid = dest.stem
    job = Job(id=jid, filename=f.filename or dest.name)
    jobs[jid] = job
    threading.Thread(target=lambda: get_engine().run_job(job, str(dest)),
                     daemon=True).start()
    return job_info(job)


@app.post("/fetch")
def fetch(url: str = Form(...), browser: str | None = Form(None)):
    _ = browser
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(400, f"bad url: {url[:100]}")
    jid = uuid.uuid4().hex[:8]
    job = Job(id=jid, filename=url[:120])
    jobs[jid] = job
    threading.Thread(target=lambda: run_url_job(job, url.strip(), DATA / jid, get_engine()), daemon=True).start()
    return job_info(job)


@app.get("/jobs/{jid}/md", response_class=PlainTextResponse)
def job_md(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    for cand in (DATA / jid).glob("*/transcript.md"):
        if cand.is_file():
            return cand.read_text(encoding="utf-8")
    raise HTTPException(404, "no transcript yet")


@app.get("/jobs/{jid}/shots/{name}")
def job_shot(jid: str, name: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    if "/" in name or not name.endswith(".jpg"):
        raise HTTPException(400, "bad name")
    for cand in (DATA / jid).glob("*/screenshots/*.jpg"):
        if cand.name == name and cand.is_file():
            return FileResponse(cand)
    raise HTTPException(404, "no such shot")


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


@app.get("/jobs/{jid}/vtt", response_class=PlainTextResponse)
def job_vtt_dl(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    return Response(job_vtt(j), media_type="text/vtt")


ResponseFormat = Literal["json", "text", "verbose_json", "srt", "vtt"]


def verbose_json(job: Job, want_words: bool) -> dict:
    resp: dict = {
        "task": "transcribe",
        "language": "russian",
        "duration": round(job.total_sec, 2),
        "text": job_text(job),
        "segments": [
            {"id": i, "seek": 0,
             "start": round(p.start, 2), "end": round(p.end, 2),
             "text": p.text, "tokens": [],
             "temperature": 0.0, "avg_logprob": 0.0,
             "compression_ratio": 1.0, "no_speech_prob": 0.0}
            for i, p in enumerate(job.phrases)
        ],
    }
    if want_words:
        resp["words"] = []
    return resp


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    request: Request,
    file: UploadFile,
    model: str = Form("gigaam-v3"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: ResponseFormat = Form("json"),  # type: ignore[assignment]
    temperature: float = Form(0.0),
):
    _ = model, language, prompt, temperature
    form = await request.form()
    granularities = form.getlist("timestamp_granularities[]") or ["segment"]
    if granularities == [""]:
        granularities = ["segment"]
    bad = [g for g in granularities if g not in ("segment", "word")]
    if bad:
        raise HTTPException(400, f"bad timestamp_granularities: {bad}")
    if "word" in granularities and response_format != "verbose_json":
        logger.warning("word timestamps requested with format %s: ignored",
                       response_format)

    dest = save_upload(file)
    job = Job(id=dest.stem, filename=file.filename or dest.name)
    get_engine().run_job(job, str(dest))
    if job.status == "error":
        raise HTTPException(500, f"transcription failed: {job.error}")

    if response_format == "json":
        return {"text": job_text(job)}
    if response_format == "text":
        return PlainTextResponse(job_text(job))
    if response_format == "srt":
        return PlainTextResponse(job_srt(job), media_type="text/plain")
    if response_format == "vtt":
        return Response(job_vtt(job), media_type="text/vtt")
    return JSONResponse(verbose_json(job, want_words="word" in granularities))
