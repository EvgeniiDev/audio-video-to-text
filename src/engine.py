from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass, field

import numpy as np

from .vad import phrase_dbfs, segment

logger = logging.getLogger("giga-transcribe")

SAMPLE_RATE = 16000
MODEL_NAME = "v3_e2e_ctc"


def decode_audio(path: str) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


@dataclass
class Phrase:
    start: float
    end: float
    text: str


@dataclass
class Job:
    id: str
    filename: str
    status: str = "queued"
    phrases: list[Phrase] = field(default_factory=list)
    total_sec: float = 0.0
    done_sec: float = 0.0
    error: str = ""


class Engine:
    def __init__(self, model_name: str = MODEL_NAME, device: str = "cpu"):
        import os

        import torch
        import gigaam

        download_root = os.environ.get("GIGAAM_CACHE", "") or None
        logger.info("loading GigaAM %s on %s (cache=%s)...",
                    model_name, device, download_root or "~/.cache/gigaam")
        self.model = gigaam.load_model(model_name, device=device,
                                       download_root=download_root)
        self.device = torch.device(device)
        self.dtype = next(self.model.parameters()).dtype
        self.lock = threading.Lock()
        logger.info("model ready")

    def transcribe_samples(self, samples: np.ndarray) -> str:
        import torch
        wav = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
        wav = wav.to(self.device, self.dtype).unsqueeze(0)
        length = torch.full([1], wav.shape[-1], device=self.device)
        with self.lock:
            encoded, encoded_len = self.model.forward(wav, length)
            decoded = self.model.decoding.decode(self.model.head, encoded, encoded_len)
        return decoded[0][0].strip()

    def run_job(self, job: Job, path: str):
        try:
            job.status = "decoding"
            samples = decode_audio(path)
            job.total_sec = len(samples) / SAMPLE_RATE
            job.status = "transcribing"
            for start, end, audio in segment(samples):
                if phrase_dbfs(audio) < -40.0:
                    job.done_sec = end
                    continue
                text = self.transcribe_samples(audio)
                if text:
                    job.phrases.append(Phrase(start, end, text))
                job.done_sec = end
            job.status = "done"
        except Exception as e:
            logger.exception("job %s failed", job.id)
            job.status = "error"
            job.error = str(e)[:500]


def job_text(job: Job) -> str:
    return "\n".join(p.text for p in job.phrases)


def _ts(sec: float) -> str:
    ms = int(sec * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def job_srt(job: Job) -> str:
    out = []
    for i, p in enumerate(job.phrases, 1):
        out.append(f"{i}\n{_ts(p.start)} --> {_ts(p.end)}\n{p.text}\n")
    return "\n".join(out)


def job_vtt(job: Job) -> str:
    out = ["WEBVTT", ""]
    for p in job.phrases:
        out.append(f"{_ts(p.start).replace(',', '.')} --> "
                   f"{_ts(p.end).replace(',', '.')}\n{p.text}\n")
    return "\n".join(out)
