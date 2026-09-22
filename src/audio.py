import subprocess
from pathlib import Path


def extract_audio(video_path: Path, audio_path: Path):
    """Extract 16 kHz mono WAV from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-ac", "1", "-ar", "16000",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")
