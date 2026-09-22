# audio-video-to-text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge video-exporter pipeline (URL download + slides + transcript.md) into giga-transcribe web server as a URL-job flow, single VAD engine.

**Architecture:** Port 6 video-exporter modules verbatim into `src/`, add `pipeline.py` orchestrator that calls `Engine.run_job` for transcription, extend `app.py` with `POST /fetch` + md/shots endpoints, extend `index.html` with URL row, extend Dockerfile with pipeline system deps. No engine/VAD changes.

**Tech Stack:** FastAPI, GigaAM v3_e2e_ctc, Silero VAD, yt-dlp, PySceneDetect, Tesseract (rus+eng), pytest + httpx TestClient.

**Spec:** `docs/superpowers/specs/2026-09-22-avtt-merge-design.md`

## Global Constraints

- Engine logic (`src/engine.py`, `src/vad.py`) unchanged — no new model, no new chunking.
- `transcriber.py` (longform/pyannote/HF_TOKEN) is NOT ported.
- No batch-from-file in web, no rerun-from in web, no extra auth.
- Python 3.11 (venv), existing requirements.txt versions stay pinned.
- Tests run with `.venv/bin/python -m pytest` (pytest + httpx installed in venv).

## Review Focus

- URL that yt-dlp cannot resolve (private/removed video) must yield job `error`, not stuck `downloading`.
- `POST /fetch` with non-URL garbage must return 400, not a hung job.
- Slide endpoints for a job without slides must return 404/empty, not 500.
- Concurrent `/fetch` while a transcription holds the engine lock must queue, not crash.
- `transcript.md` image links must resolve via the shots endpoint (relative paths break when served).

---

### Task 1: Port pipeline modules

**Files:**
- Create: `src/downloader.py`, `src/audio.py`, `src/workdir.py`, `src/frame_sampler.py`, `src/frame_filter.py`, `src/renderer.py`
- Test: `tests/test_pipeline_units.py`

**Interfaces:**
- Consumes: nothing (verbatim port, package renamed `video_exporter` → `src`).
- Produces: `downloader.download(url, output_path, browser)`, `downloader.extract_video_id(url, browser)`, `audio.extract_audio(video, wav)`, `WorkDir(video_id, base)` with `.video/.audio/.transcript_jsonl/.frames_dir/.screenshots_dir/.transcript_md`, `frame_sampler.sample_frames(video, frames_dir, sample_interval, phash_threshold, scene_threshold) -> list[int]`, `frame_filter.filter_frames(frames_dir, screenshots_dir, kept_ms, ...) -> list[int]`, `renderer.render(jsonl, screenshots_dir, output_md)`.

- [ ] **Step 1: Copy the six files verbatim**

Run: `cp /tmp/video-exporter/src/{downloader,audio,workdir,frame_sampler,frame_filter,renderer}.py src/`
Then: `grep -rn "video_exporter" src/downloader.py src/audio.py src/workdir.py src/frame_sampler.py src/frame_filter.py src/renderer.py || true`
Expected: no matches (these six files have no intra-package imports).

- [ ] **Step 2: Write the failing test**

```python
from pathlib import Path
from src.workdir import WorkDir
from src.renderer import render
import json


def test_workdir_layout(tmp_path):
    wd = WorkDir("abc123", base=str(tmp_path))
    assert wd.video.name == "video.mp4"
    assert wd.transcript_md.name == "transcript.md"
    assert wd.frames_dir.is_dir() and wd.screenshots_dir.is_dir()


def test_render_empty_segments(tmp_path):
    jl = tmp_path / "t.jsonl"
    jl.write_text("")
    out = tmp_path / "transcript.md"
    shots = tmp_path / "shots"
    shots.mkdir()
    render(jl, shots, out)
    assert out.read_text() == ""


def test_render_segment_with_shot(tmp_path):
    jl = tmp_path / "t.jsonl"
    jl.write_text(json.dumps({"start": 0.0, "end": 10.0, "text": "hello world"}) + "\n")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "frame_5000.jpg").write_bytes(b"fake")
    out = tmp_path / "transcript.md"
    render(jl, shots, out)
    text = out.read_text()
    assert "hello world" in text
    assert "frame_5000.jpg" in text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline_units.py -v`
Expected: FAIL with "No module named 'src'" or collection error (no `tests/__init__.py` / conftest path setup).

- [ ] **Step 4: Make imports work (minimal)**

Create `tests/__init__.py` (empty). Repo root is CWD so `src.` imports resolve. No sys.path hacks, no conftest.
Run: `.venv/bin/python -m pytest tests/test_pipeline_units.py -v`
Expected: collection error mentions `pandas`/`imagehash` missing on `src.frame_filter` import — renderer/workdir tests themselves need no heavy deps.

- [ ] **Step 5: Defer heavy-dep import, keep light tests green**

Edit `tests/test_pipeline_units.py`: move `frame_sampler`/`frame_filter` imports into test functions that are skipped if deps missing:

```python
import pytest
pillow = pytest.importorskip("PIL", reason="pipeline slide deps not installed")
```

Wait — simpler: do NOT import sampler/filter at module level at all in this task. Only workdir + renderer (stdlib only). Sampler/filter get exercised in Task 3 with installed deps.
Run: `.venv/bin/python -m pytest tests/test_pipeline_units.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/downloader.py src/audio.py src/workdir.py src/frame_sampler.py src/frame_filter.py src/renderer.py tests/test_pipeline_units.py tests/__init__.py
git commit -m "feat: port video-exporter pipeline modules"
```

### Task 2: Pipeline orchestrator on Engine

**Files:**
- Create: `src/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Engine.run_job(job, wav_path)` + `Job`/`Phrase` from `src.engine`; the six ported modules from Task 1.
- Produces: `run_url_job(job: Job, url: str, data_dir: Path, engine: Engine, make_slides: bool = True) -> None` — sets `job.status` through `downloading → decoding → transcribing → slides → done` (or `error`), writes `job.phrases`, `job.total_sec/done_sec`, leaves `transcript.jsonl` + `transcript.md` + screenshots under `data_dir/<jobid>/`.

- [ ] **Step 1: Write the failing test (transcription stubbed)**

```python
from pathlib import Path
from src.engine import Job
from src import pipeline


class FakeEngine:
    def run_job(self, job, wav_path):
        from src.engine import Phrase
        job.status = "transcribing"
        job.total_sec = 10.0
        job.phrases.append(Phrase(0.0, 10.0, "stub text"))
        job.done_sec = 10.0
        job.status = "done"


def test_run_url_job_bad_url(tmp_path):
    job = Job(id="u1", filename="http://nope.invalid/xyz")
    pipeline.run_url_job(job, "http://nope.invalid/xyz", tmp_path, FakeEngine(), make_slides=False)
    assert job.status == "error"
    assert job.error != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with "No module named 'src.pipeline'" / "has no attribute 'run_url_job'".

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path

from .downloader import download, extract_video_id
from .audio import extract_audio
from .engine import Engine, Job
from .workdir import WorkDir

logger = logging.getLogger("audio-video-to-text")


def run_url_job(job: Job, url: str, data_dir: Path, engine: Engine, make_slides: bool = True):
    try:
        job.status = "downloading"
        video_id = extract_video_id(url, None)
        wd = WorkDir(video_id, base=str(data_dir))
        if not wd.is_done("download"):
            download(url, wd.video, None)
            wd.mark_done("download")
        if not wd.is_done("audio"):
            extract_audio(wd.video, wd.audio)
            wd.mark_done("audio")
        job.filename = f"{video_id}.mp4"
        engine.run_job(job, str(wd.audio))
        if job.status == "error":
            return
        with open(wd.transcript_jsonl, "w", encoding="utf-8") as f:
            for p in job.phrases:
                f.write(json.dumps({"start": p.start, "end": p.end, "text": p.text}, ensure_ascii=False) + "\n")
        if make_slides:
            from .frame_filter import filter_frames
            from .frame_sampler import sample_frames
            from .renderer import render
            job.status = "slides"
            kept_ms = sample_frames(wd.video, wd.frames_dir)
            filter_frames(wd.frames_dir, wd.screenshots_dir, kept_ms)
            render(wd.transcript_jsonl, wd.screenshots_dir, wd.transcript_md)
        job.status = "done"
    except Exception as e:
        logger.exception("url job %s failed", job.id)
        job.status = "error"
        job.error = str(e)[:500]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_pipeline_units.py -v`
Expected: PASS. (Bad-URL test exercises the `except` path via real `extract_video_id` raising; no network success needed.)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: url-job orchestrator on Engine"
```

### Task 3: Web API — /fetch + md/shots endpoints

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_fetch_api.py`

**Interfaces:**
- Consumes: `pipeline.run_url_job` from Task 2; existing `jobs` dict, `job_info`, `Job`.
- Produces: `POST /fetch` (form field `url`, optional `browser`) → job_info with `stage`; `GET /jobs/{id}/md`; `GET /jobs/{id}/shots/{name}`; `job_info` gains `stage` key (= `status`).

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_fetch_garbage_rejected():
    r = client.post("/fetch", data={"url": "not a url"})
    assert r.status_code == 400


def test_md_missing_job():
    r = client.get("/jobs/nonexistent/md")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fetch_api.py -v`
Expected: FAIL — 404 on `/fetch` (no such route), and `/jobs/nonexistent/md` 404 passes only after route exists (currently 404 from missing route, coincidentally; first assertion is the real fail).

- [ ] **Step 3: Minimal implementation in `src/app.py`**

```python
@app.post("/fetch")
def fetch(url: str = Form(...), browser: str | None = Form(None)):
    from urllib.parse import urlparse
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(400, f"bad url: {url[:100]}")
    jid = uuid.uuid4().hex[:8]
    job = Job(id=jid, filename=url[:120])
    jobs[jid] = job
    threading.Thread(target=lambda: run_url_job(job, url.strip(), DATA, get_engine()), daemon=True).start()
    return job_info(job)


@app.get("/jobs/{jid}/md", response_class=PlainTextResponse)
def job_md(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    for cand in DATA.glob(f"*/transcript.md"):
        if j.filename.startswith(cand.parent.name):
            return cand.read_text(encoding="utf-8")
    raise HTTPException(404, "no transcript yet")


@app.get("/jobs/{jid}/shots/{name}")
def job_shot(jid: str, name: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "no such job")
    if "/" in name or not name.endswith(".jpg"):
        raise HTTPException(400, "bad name")
    for cand in DATA.glob(f"*/screenshots/{name}"):
        if j.filename.startswith(cand.parents[1].name):
            return FileResponse(cand)
    raise HTTPException(404, "no such shot")
```

Also add `from .pipeline import run_url_job` import. `stage` = reuse `status` value in `job_info` (add `"stage": j.status`).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (all files).

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_fetch_api.py
git commit -m "feat: /fetch endpoint, md and shots download"
```

### Task 4: Frontend URL row

**Files:**
- Modify: `static/index.html`
- Test: manual (open page, paste URL, watch stages); automated: `tests/test_frontend.py` asserts the served HTML contains `id="urlrow"` and `/fetch`.

**Interfaces:**
- Consumes: `POST /fetch`, `GET /jobs/{id}` (+ `stage`), `/jobs/{id}/md` from Task 3.
- Produces: URL input + button; URL job cards showing stage text and `.md` link when done.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from src.app import app

client = TestClient(app)


def test_index_has_url_row():
    html = client.get("/").text
    assert 'id="urlrow"' in html
    assert "/fetch" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_frontend.py -v`
Expected: FAIL — `id="urlrow"` missing.

- [ ] **Step 3: Minimal HTML/JS addition**

Insert after the `#drop` div:

```html
<div id="urlrow" style="display:flex;gap:8px;margin-top:12px">
<input id="url" placeholder="Ссылка YouTube / Boosty…" style="flex:1;padding:10px;border-radius:8px;border:1px solid #444;background:#1e2126;color:#e8e8e8">
<button id="go" style="padding:10px 16px;border-radius:8px;border:1px solid #444;background:#1e2126;color:var(--acc);cursor:pointer">➔</button>
</div>
<script>
document.getElementById('go').onclick = async () => {
  const url = document.getElementById('url').value.trim();
  if (!url) return;
  const fd = new FormData(); fd.append('url', url);
  const r = await fetch('/fetch', {method:'POST', body:fd});
  if (!r.ok) { alert('Ошибка: ' + await r.text()); return; }
  render(await r.json());
};
</script>
```

And in `render()`: stage label map add `downloading:'качаю…', slides:'ищу слайды…'`; done buttons add `<a href="/jobs/${j.id}/md" download="transcript.md">.md</a>`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/index.html tests/test_frontend.py
git commit -m "feat: url input row in web ui"
```

### Task 5: Deps — requirements + Dockerfile + README

**Files:**
- Modify: `requirements.txt`, `Dockerfile`, `README.md`
- Test: `docker compose build` (or at minimum `.venv/bin/python -c "import yt_dlp"` after `uv pip install`); no pytest file — verify by build output.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: working image with pipeline system deps; README documenting link flow.

- [ ] **Step 1: Add Python deps to requirements.txt**

```
yt-dlp
scenedetect[opencv]
pytesseract
Pillow
imagehash
pandas
```

Pin nothing new (follow existing style: unpinned for these, like upstream video-exporter).

- [ ] **Step 2: Add system layer to Dockerfile**

In `base` stage apt install add: `tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng` (ffmpeg already there).

- [ ] **Step 3: Update README**

Add section: paste link → stages → transcript.md + slides. One paragraph + two curl lines (`POST /fetch`, `GET /jobs/<id>/md`). Rename title mentions giga-transcribe → audio-video-to-text only in the new section; full rename happens at repo move.

- [ ] **Step 4: Verify**

Run: `uv pip install --python .venv/bin/python yt-dlp scenedetect[opencv] pytesseract Pillow imagehash pandas 2>&1 | tail -2`
Then: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS, imports of sampler/filter now resolvable.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt Dockerfile README.md
git commit -m "chore: pipeline deps, docker layer, readme link flow"
```
