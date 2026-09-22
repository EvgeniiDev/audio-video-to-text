"""VAD segmentation for files via Silero VAD (snakers4/silero-vad).

Takes mono float32 16 kHz audio of ANY length, yields
(start_sec, end_sec, samples) per speech phrase. Model is loaded once
(weights bundled in the pip package, works offline) and reused.
"""
from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000

_model = None
_model_lock = threading.Lock()


def get_vad_model():
    """Silero VAD model, lazy singleton (thread-safe)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from silero_vad import load_silero_vad

                _model = load_silero_vad()
    return _model


def phrase_dbfs(audio: np.ndarray) -> float:
    """Level of a phrase in dBFS (for silence filtering)."""
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)) + 1e-10)
    return 20.0 * np.log10(rms)


def speech_timestamps(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    threshold: float = 0.5,
    min_speech_sec: float = 0.25,
    min_silence_sec: float = 0.5,
    pad_sec: float = 0.2,
    max_segment: float = 25.0,
) -> list[tuple[float, float]]:
    """Speech regions as (start_sec, end_sec). Input length is unlimited:
    Silero iterates internally in ~32 ms windows with O(n) time."""
    import torch
    from silero_vad import get_speech_timestamps

    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Silero VAD needs {SAMPLE_RATE} Hz, got {sample_rate}")
    model = get_vad_model()
    wav = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
    with _model_lock:  # JIT model holds recurrent state; serialize access
        model.reset_states()
        with torch.inference_mode():
            ts = get_speech_timestamps(
                wav,
                model,
                return_seconds=True,
                threshold=threshold,
                min_speech_duration_ms=int(min_speech_sec * 1000),
                min_silence_duration_ms=int(min_silence_sec * 1000),
                speech_pad_ms=int(pad_sec * 1000),
                max_speech_duration_s=max_segment,
            )
    return [(float(d["start"]), float(d["end"])) for d in ts]


def segment(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    max_segment: float = 25.0,
    **kwargs,
) -> tuple[float, float, np.ndarray]:
    """Split mono float32 audio into speech phrases.

    Yields (start_sec, end_sec, audio) tuples. Same interface as the old
    EnergyVAD segmenter, so engine.py needs no changes. Extra kwargs
    (block_sec, silence_hangover, ...) are accepted and ignored for
    backward compatibility.
    """
    for start, end in speech_timestamps(samples, sample_rate, max_segment=max_segment):
        s0, s1 = int(start * sample_rate), int(end * sample_rate)
        yield (start, end, samples[s0:s1])
