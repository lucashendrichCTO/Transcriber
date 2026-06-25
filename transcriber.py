from typing import Optional

import numpy as np
from faster_whisper import WhisperModel

_model: Optional[WhisperModel] = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        print("Loading Whisper 'base' model (downloads ~142 MB on first run)…")
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        print("Whisper model ready.")
    return _model


def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = 16000, skip_secs: float = 0.0) -> str:
    """Transcribe raw 16-bit mono PCM audio bytes and return the transcript.

    skip_secs: exclude segments that end before this timestamp. Used to discard
    the overlap prefix prepended for context when stitching chunks.
    """
    if not pcm_bytes:
        return ""

    model = get_model()

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    segments, _ = model.transcribe(
        audio,
        language="en",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    parts = []
    for seg in segments:
        if seg.end <= skip_secs:
            continue  # inside the overlap prefix — already in previous segment
        parts.append(seg.text.strip())
    return " ".join(parts).strip()
