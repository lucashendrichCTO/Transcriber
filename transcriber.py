import os
import tempfile
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


def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw 16-bit PCM audio bytes and return the full transcript string."""
    model = get_model()

    # Convert raw PCM bytes to float32 numpy array
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    segments, _ = model.transcribe(
        audio,
        language="en",
        vad_filter=True,           # skip silence
        vad_parameters={"min_silence_duration_ms": 300},
    )

    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_webm(audio_bytes: bytes) -> str:
    """Transcribe webm/ogg audio bytes by writing to a temp buffer Whisper can read."""
    model = get_model()
    suffix = ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        segments, _ = model.transcribe(
            tmp_path,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        os.unlink(tmp_path)
