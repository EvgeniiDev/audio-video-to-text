import json
import re
from pathlib import Path

# If a screenshot timestamp is within this many seconds of a segment boundary,
# attach it at the boundary instead of splitting the segment text.
BOUNDARY_TOLERANCE_SEC = 2.0

_FRAME_NAME_RE = re.compile(r"^frame_(\d+)\.jpg$")


def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _ts_ms_from_screenshots_dir(screenshots_dir: Path) -> list[int]:
    """Recover ts_ms list by scanning frame_<ms>.jpg names."""
    result = []
    if not screenshots_dir.exists():
        return result
    for p in screenshots_dir.iterdir():
        m = _FRAME_NAME_RE.match(p.name)
        if m:
            result.append(int(m.group(1)))
    return sorted(result)


def _split_text_proportionally(text: str, cuts_ratio: list[float]) -> list[str]:
    """
    Split text into len(cuts_ratio)+1 chunks at word boundaries closest to each ratio.
    cuts_ratio is a sorted list of values in [0, 1].
    """
    words = text.split()
    if not words:
        return [""] * (len(cuts_ratio) + 1)

    n = len(words)
    chunks: list[str] = []
    prev_idx = 0
    for r in cuts_ratio:
        idx = max(prev_idx, min(n, round(r * n)))
        chunks.append(" ".join(words[prev_idx:idx]))
        prev_idx = idx
    chunks.append(" ".join(words[prev_idx:]))
    return chunks


def render(
    transcript_jsonl: Path,
    screenshots_dir: Path,
    output_md: Path,
):
    """Merge transcript segments and screenshots into a Markdown file.

    Screenshots are discovered by scanning screenshots_dir for
    frame_<ms>.jpg files. Any screenshot whose timestamp falls inside a
    segment more than BOUNDARY_TOLERANCE_SEC from either edge splits the
    segment text proportionally by time, so the image lands near the
    matching speech.
    """
    segments = []
    with open(transcript_jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                segments.append(json.loads(line))

    screenshots = [{"ts_ms": ms} for ms in _ts_ms_from_screenshots_dir(screenshots_dir)]

    if not segments:
        output_md.write_text("", encoding="utf-8")
        return

    def find_segment(ts_sec: float) -> int:
        # Containment check first; fall back to nearest by midpoint.
        for i, seg in enumerate(segments):
            if seg["start"] <= ts_sec <= seg["end"]:
                return i
        return min(
            range(len(segments)),
            key=lambda i: abs(
                (segments[i]["start"] + segments[i]["end"]) / 2 - ts_sec
            ),
        )

    # Each segment gets a list of (ts_sec, ts_ms, position) entries.
    # position is "before", "after", or "mid" (split text proportionally).
    seg_shots: dict[int, list[dict]] = {}
    for shot in screenshots:
        ts_sec = shot["ts_ms"] / 1000.0
        i = find_segment(ts_sec)
        seg = segments[i]
        duration = max(0.0, seg["end"] - seg["start"])

        if ts_sec <= seg["start"] + BOUNDARY_TOLERANCE_SEC:
            position = "before"
        elif ts_sec >= seg["end"] - BOUNDARY_TOLERANCE_SEC:
            position = "after"
        elif duration > 0:
            position = "mid"
        else:
            position = "after"

        seg_shots.setdefault(i, []).append(
            {"ts_sec": ts_sec, "ts_ms": shot["ts_ms"], "position": position}
        )

    lines: list[str] = []
    for i, seg in enumerate(segments):
        lines.append(f"<!-- t={_fmt_time(seg['start'])} -->")

        shots = sorted(seg_shots.get(i, []), key=lambda s: s["ts_sec"])
        before = [s for s in shots if s["position"] == "before"]
        mid = [s for s in shots if s["position"] == "mid"]
        after = [s for s in shots if s["position"] == "after"]

        for s in before:
            lines.append(f"![](screenshots/frame_{s['ts_ms']}.jpg)")
            lines.append("")

        if mid:
            duration = seg["end"] - seg["start"]
            ratios = [(s["ts_sec"] - seg["start"]) / duration for s in mid]
            chunks = _split_text_proportionally(seg["text"], ratios)
            for j, chunk in enumerate(chunks):
                if chunk:
                    lines.append(chunk)
                if j < len(mid):
                    lines.append("")
                    lines.append(f"![](screenshots/frame_{mid[j]['ts_ms']}.jpg)")
                    lines.append("")
        else:
            lines.append(seg["text"])

        for s in after:
            lines.append("")
            lines.append(f"![](screenshots/frame_{s['ts_ms']}.jpg)")

        lines.append("")

    output_md.write_text("\n".join(lines), encoding="utf-8")
