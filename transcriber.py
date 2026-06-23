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
    """Transcribe raw 16-bit mono PCM audio bytes and return the full transcript.

    The browser sends raw PCM (no container), so every slice — including a
    partial buffer mid-recording — is always decodable. This avoids the
    truncated-webm problem where ffmpeg decodes zero frames from an
    unfinalized MediaRecorder stream.
    """
    if not pcm_bytes:
        return ""

    model = get_model()

    # Raw 16-bit signed PCM -> float32 in [-1, 1]
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    segments, _ = model.transcribe(
        audio,
        language="en",
        vad_filter=True,           # skip silence
        vad_parameters={"min_silence_duration_ms": 300},
    )

    return " ".join(seg.text.strip() for seg in segments).strip()
