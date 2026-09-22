import json
import os
from pathlib import Path
from datetime import datetime

STAGES = ["download", "audio", "transcript", "frames", "filter", "render"]


class WorkDir:
    def __init__(self, video_id: str, base: str = "work"):
        self.root = Path(base) / video_id
        self.video = self.root / "video.mp4"
        self.audio = self.root / "audio.wav"
        self.transcript_jsonl = self.root / "transcript.jsonl"
        self.frames_dir = self.root / "frames"
        self.screenshots_dir = self.root / "screenshots"
        self.transcript_md = self.root / "transcript.md"
        self.manifest = self.root / "manifest.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(exist_ok=True)
        self.screenshots_dir.mkdir(exist_ok=True)

    def done_path(self, stage: str) -> Path:
        return self.root / f".done.{stage}"

    def is_done(self, stage: str) -> bool:
        return self.done_path(stage).exists()

    def mark_done(self, stage: str):
        self.done_path(stage).touch()

    def reset_from(self, stage: str):
        idx = STAGES.index(stage)
        for s in STAGES[idx:]:
            p = self.done_path(s)
            if p.exists():
                p.unlink()

    def write_manifest(self, data: dict):
        existing = {}
        if self.manifest.exists():
            with open(self.manifest) as f:
                existing = json.load(f)
        existing.update(data)
        existing["updated_at"] = datetime.utcnow().isoformat()
        with open(self.manifest, "w") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
