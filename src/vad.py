from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000

_model = None
_model_lock = threading.Lock()


def get_vad_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from silero_vad import load_silero_vad

                _model = load_silero_vad()
    return _model


def phrase_dbfs(audio: np.ndarray) -> float:
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
    import torch
    from silero_vad import get_speech_timestamps

    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Silero VAD needs {SAMPLE_RATE} Hz, got {sample_rate}")
    model = get_vad_model()
    wav = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
    with _model_lock:
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
    for start, end in speech_timestamps(samples, sample_rate, max_segment=max_segment):
        s0, s1 = int(start * sample_rate), int(end * sample_rate)
        yield (start, end, samples[s0:s1])
