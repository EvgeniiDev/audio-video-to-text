from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .downloader import download, extract_video_id
from .audio import extract_audio
from .engine import Engine, Job
from .workdir import WorkDir

logger = logging.getLogger("audio-video-to-text")


def run_url_job(job: Job, url: str, data_dir: Path, engine: Engine, make_slides: bool = True, browser: str | None = None, cookie: str | None = None) -> None:
    try:
        job.status = "downloading"
        video_id = re.sub(r"[^\w-]", "_", extract_video_id(url, browser, cookie))
        wd = WorkDir(video_id, base=str(data_dir))
        if not wd.is_done("download"):
            download(url, wd.video, browser, cookie)
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
        job.error = (str(e) or repr(e))[:500]
