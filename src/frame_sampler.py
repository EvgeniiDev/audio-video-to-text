import subprocess
import json
from pathlib import Path

import imagehash
from PIL import Image


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


def _phash(img_path: Path) -> imagehash.ImageHash:
    return imagehash.phash(Image.open(img_path))


def _extract_frame(video_path: Path, ts_sec: float, out_path: Path):
    """
    Extract a single frame at ts_sec. Uses combined input+output seek for
    accuracy: a coarse input-seek skips most of the file by keyframes, then
    a fine output-seek lands precisely on the requested timestamp.
    """
    pre_seek = max(0.0, ts_sec - 2.0)
    fine_seek = ts_sec - pre_seek
    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error",
        "-ss", f"{pre_seek:.3f}",
        "-i", str(video_path),
        "-ss", f"{fine_seek:.3f}",
        "-frames:v", "1",
        "-an",
        "-q:v", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def get_scene_cuts(video_path: Path, threshold: float = 27.0) -> list[float]:
    """Return list of scene cut timestamps in seconds using PySceneDetect."""
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()
    cuts = []
    for scene in scene_list:
        t = scene[0].get_seconds()
        if t > 0:
            cuts.append(t)
    return cuts


def sample_frames(
    video_path: Path,
    frames_dir: Path,
    sample_interval: int = 3,
    phash_threshold: int = 3,
    scene_threshold: float = 27.0,
) -> list[int]:
    """
    Extract candidate frames. Returns sorted list of timestamps in ms.
    Strategy:
      (a) scene-cut timestamps (hard transitions between shots/slides)
      (b) periodic every sample_interval seconds (captures incremental
          changes within a scene: bullet animations, live coding, etc.)
      (c) adjacency pHash filter: skip pixel-identical consecutive samples.
          NOTE: pHash here compares only TIME-ADJACENT samples — it is never
          used to dedup unrelated slides. Slide-level dedup (same template,
          different text) is done in frame_filter via OCR-Jaccard.
    """
    duration = get_video_duration(video_path)
    scene_cuts = get_scene_cuts(video_path, threshold=scene_threshold)

    # Bucket by ms to avoid near-duplicate float timestamps from scene cuts vs periodic.
    candidates_ms: set[int] = {_ms(t) for t in scene_cuts}
    t = 0.0
    while t <= duration:
        candidates_ms.add(_ms(t))
        t += sample_interval
    near_end = duration - 0.5
    if near_end > 0:
        candidates_ms.add(_ms(near_end))

    sorted_candidates = sorted(candidates_ms)

    kept_ms: list[int] = []
    prev_hash = None

    for ms in sorted_candidates:
        ts = ms / 1000.0
        if ts < 0 or ts > duration:
            continue

        out_path = frames_dir / f"frame_{ms}.jpg"

        try:
            _extract_frame(video_path, ts, out_path)
        except subprocess.CalledProcessError:
            continue

        if not out_path.exists() or out_path.stat().st_size == 0:
            continue

        curr_hash = _phash(out_path)

        # Adjacency filter: skip pixel-identical to previous kept frame.
        if prev_hash is not None and curr_hash - prev_hash <= phash_threshold:
            out_path.unlink(missing_ok=True)
            continue

        prev_hash = curr_hash
        kept_ms.append(ms)

    return sorted(kept_ms)
