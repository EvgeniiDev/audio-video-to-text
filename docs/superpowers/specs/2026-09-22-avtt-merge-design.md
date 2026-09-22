# Merge giga-transcribe + video-exporter → audio-video-to-text

## Intent

Merge two repos owned by EvgeniiDev into one, keeping the video-exporter
star and git history (rename to `EvgeniiDev/audio-video-to-text`).
giga-transcribe is archived with a README pointer after the merge.
Single product: drop a file or paste a link — get text + subtitles +
transcript.md with slides. Agreed scope A, approach 2 (pipeline becomes
part of the web UI), single engine (VAD chunking, `v3_e2e_ctc`).
Assumption: rename preserves stars/history (standard GitHub rename).

## Engine (unchanged logic)

`src/engine.py` + `src/vad.py` stay as-is: ffmpeg → Silero VAD phrases
(≤25 s) → GigaAM `v3_e2e_ctc` → `Job.phrases`. CTC vs RNNT comparison
showed ~0.8 pp WER gap, not worth slower CPU inference; `transcriber.py`
(longform/pyannote, needs HF_TOKEN) from video-exporter is dropped.
Punctuation/casing come from the `e2e` model, no post-processing.

## Pipeline (ported from video-exporter)

New `src/pipeline.py`: stages download → audio → frames → filter →
render, reusing video-exporter `downloader.py`, `audio.py`,
`frame_sampler.py`, `frame_filter.py`, `renderer.py`, `workdir.py`
verbatim except: transcript stage replaced by `Engine.run_job` on the
extracted wav; progress reported into `Job` (stage + done_sec).
No `--rerun-from` in web (retry = new job); CLI keeps thin local run.

## Web API (`src/app.py`)

- `POST /upload` (unchanged): file → job → thread → `run_job`.
- `POST /fetch {url, browser?}` (new): job with `status=downloading` →
  yt-dlp into `data/` → `run_job` → optional slides → `done`.
  Boosty cookies via env/mount, not server browser.
- `GET /jobs/{id}`: add `stage` + preview; new `GET /jobs/{id}/md`
  (transcript.md) and `/jobs/{id}/shots/{name}` (slide images).
- `/v1/audio/transcriptions` unchanged (short files, sync).

## Frontend (`static/index.html`)

Two entries, one job list: existing drag-and-drop block on top, new
URL row below (input + button). URL job cards show stage
(`качаю…` / `транскрибирую…` / `ищу слайды…`) + same ETA logic;
done cards add `.md` download link next to .txt/.srt.

## Docker

giga-transcribe Dockerfile as base, plus one layer: `yt-dlp`,
`tesseract-ocr + rus/eng`, `scenedetect`, `pytesseract/Pillow/imagehash`.
Entrypoint/weights flow unchanged. `data/` holds uploads + per-job
artifacts (video, audio, frames, screenshots, transcript.md).

## Out of scope (YAGNI)

No batch-from-file in web, no rerun-from in web, no extra auth,
no second model option. CLI: thin local run or drop at merge time.
