"""VAD segmentation for files. Same idea as qwen_talker streaming ASR
(EnergyVAD + hangover + max segment), but fed with blocks decoded from a
file instead of a microphone. Yields (start_sec, end_sec, samples) per phrase.
"""
from __future__ import annotations

import numpy as np


class EnergyVAD:
    """Adaptive energy VAD, block-wise. Port of qwen_talker/src/asr/realtime_asr."""

    def __init__(self, margin_db: float = 10.0, abs_floor_db: float = -55.0):
        self.margin_db = margin_db
        self.abs_floor_db = abs_floor_db
        self.noise_db = -60.0
        self._initialized = False

    @staticmethod
    def _dbfs(block: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)) + 1e-10)
        return 20.0 * np.log10(rms)

    def is_speech(self, block: np.ndarray) -> bool:
        level = self._dbfs(block)
        if not self._initialized:
            self.noise_db = level
            self._initialized = True
        threshold = max(self.noise_db + self.margin_db, self.abs_floor_db)
        speech = level > threshold
        if not speech:
            self.noise_db = 0.9 * self.noise_db + 0.1 * level
        return speech


def phrase_dbfs(audio: np.ndarray) -> float:
    """Level of a phrase in dBFS (for silence filtering)."""
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)) + 1e-10)
    return 20.0 * np.log10(rms)


def segment(
    samples: np.ndarray,
    sample_rate: int = 16000,
    block_sec: float = 0.1,
    silence_hangover: float = 0.8,
    min_speech: float = 0.8,
    pre_roll: float = 0.3,
    max_segment: float = 25.0,
    vad_margin: float = 10.0,
):
    """Split mono float32 audio into speech phrases.

    Yields (start_sec, end_sec, audio) tuples. Times are in seconds.
    """
    block = int(sample_rate * block_sec)
    vad = EnergyVAD(margin_db=vad_margin)
    hangover_blocks = max(1, int(round(silence_hangover / block_sec)))
    min_blocks = max(1, int(round(min_speech / block_sec)))
    pre_roll_blocks = max(0, int(round(pre_roll / block_sec)))
    max_blocks = int(round(max_segment / block_sec))

    n_blocks = (len(samples) + block - 1) // block
    pre: list[np.ndarray] = []
    seg: list[np.ndarray] = []
    seg_start = 0
    active = False
    silence_run = 0

    def finalize(end_block: int):
        nonlocal seg, active, silence_run
        if seg and len(seg) >= min_blocks:
            audio = np.concatenate(seg)
            yield (seg_start * block_sec, end_block * block_sec, audio)
        seg = []
        active = False
        silence_run = 0

    for i in range(n_blocks):
        blk = samples[i * block:(i + 1) * block]
        speech = vad.is_speech(blk)
        if not active:
            pre.append(blk)
            if len(pre) > pre_roll_blocks:
                pre.pop(0)
            if speech:
                active = True
                seg = list(pre)
                seg_start = i - len(pre) + 1
                pre = []
                silence_run = 0
            continue
        seg.append(blk)
        silence_run = silence_run + 1 if not speech else 0
        if silence_run >= hangover_blocks or len(seg) >= max_blocks:
            yield from finalize(i + 1)
    yield from finalize(n_blocks)
