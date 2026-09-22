import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image


def _ocr_tokens(text: str) -> set[str]:
    """Lowercase alphanum tokens >= 3 chars."""
    return {
        t.lower()
        for t in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", text)
        if len(t) >= 3
    }


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def score_frame(img_path: Path, langs: str = "rus+eng") -> dict:
    """Return OCR data for a frame. Returns dict with keys: chars, words, mean_conf, coverage, text, tokens."""
    import pandas as pd

    img = Image.open(img_path)
    w, h = img.size
    frame_area = w * h

    try:
        data = pytesseract.image_to_data(
            img,
            lang=langs,
            output_type=pytesseract.Output.DATAFRAME,
        )
    except Exception as e:
        print(f"[WARN] OCR failed on {img_path.name}: {e}", file=sys.stderr)
        return {
            "chars": 0,
            "words": 0,
            "mean_conf": 0.0,
            "coverage": 0.0,
            "text": "",
            "tokens": set(),
        }

    # Filter valid words (fillna before .str to avoid mixed-type errors)
    data["text"] = data["text"].fillna("").astype(str)
    valid = data[
        (data["conf"] >= 0)
        & (data["text"].str.strip() != "")
    ]
    if valid.empty:
        return {
            "chars": 0,
            "words": 0,
            "mean_conf": 0.0,
            "coverage": 0.0,
            "text": "",
            "tokens": set(),
        }

    text = " ".join(valid["text"].tolist())
    chars = len(text.replace(" ", ""))
    words = len(valid)
    mean_conf = float(valid["conf"].mean())

    # True bbox union via rasterized mask (handles disjoint text regions correctly:
    # logo-top + caption-bottom won't fake high coverage like an envelope would).
    if frame_area > 0:
        mask = np.zeros((h, w), dtype=np.uint8)
        for left, top, bw, bh in zip(
            valid["left"].astype(int),
            valid["top"].astype(int),
            valid["width"].astype(int),
            valid["height"].astype(int),
        ):
            x0 = max(0, left)
            y0 = max(0, top)
            x1 = min(w, left + bw)
            y1 = min(h, top + bh)
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = 1
        coverage = float(mask.sum()) / frame_area
    else:
        coverage = 0.0

    tokens = _ocr_tokens(text)

    return {
        "chars": chars,
        "words": words,
        "mean_conf": mean_conf,
        "coverage": coverage,
        "text": text,
        "tokens": tokens,
    }


def filter_frames(
    frames_dir: Path,
    screenshots_dir: Path,
    kept_ms: list[int],
    ocr_min_chars: int = 40,
    ocr_min_words: int = 5,
    ocr_min_confidence: float = 60.0,
    ocr_min_coverage: float = 0.08,
    jaccard_threshold: float = 0.85,
    ocr_langs: str = "rus+eng",
) -> list[int]:
    """
    Apply OCR slide-score filter then OCR-Jaccard dedup.
    Copies kept frames to screenshots_dir (which serves as the persistent
    output — ts_ms is parsed back from the file name by the renderer).
    Returns sorted list of kept ts_ms.
    """
    # Step 1: OCR scoring + slide threshold.
    scored: list[dict] = []
    for ms in sorted(kept_ms):
        img_path = frames_dir / f"frame_{ms}.jpg"
        if not img_path.exists():
            continue
        s = score_frame(img_path, langs=ocr_langs)
        if (
            s["chars"] >= ocr_min_chars
            and s["words"] >= ocr_min_words
            and s["mean_conf"] >= ocr_min_confidence
            and s["coverage"] >= ocr_min_coverage
        ):
            scored.append({"ts_ms": ms, **s})

    # Step 2: OCR-Jaccard dedup (chronological, keep more-token version).
    kept: list[dict] = []
    for item in scored:
        if not kept:
            kept.append(item)
            continue
        prev = kept[-1]
        if _jaccard(prev["tokens"], item["tokens"]) >= jaccard_threshold:
            if len(item["tokens"]) > len(prev["tokens"]):
                kept[-1] = item
        else:
            kept.append(item)

    # Step 3: Clear stale screenshots from previous runs, then copy fresh ones.
    for stale in screenshots_dir.glob("*.jpg"):
        stale.unlink()
    for item in kept:
        src = frames_dir / f"frame_{item['ts_ms']}.jpg"
        dst = screenshots_dir / f"frame_{item['ts_ms']}.jpg"
        shutil.copy2(src, dst)

    return sorted(item["ts_ms"] for item in kept)
