import os
from typing import Optional

import numpy as np
from faster_whisper import WhisperModel

from logutil import make_file_logger

_model: Optional[WhisperModel] = None

# A double-clicked desktop app has no visible stdout, so plain print() here
# would silently vanish — only wrap with the file logger in desktop mode
# (browser mode has a real terminal, where plain print() is fine).
_log = (
    make_file_logger(os.environ.get("TRANSCRIBER_APP_NAME", "Transcriber"))
    if os.environ.get("TRANSCRIBER_DESKTOP") == "1"
    else print
)


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _log("Loading Whisper 'base' model (downloads ~142 MB on first run)…")
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        _log("Whisper model ready.")
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
        vad_parameters={"min_silence_duration_ms": 300, "threshold": 0.3},
    )

    parts = []
    for seg in segments:
        if seg.end <= skip_secs:
            continue  # inside the overlap prefix — already in previous segment
        parts.append(seg.text.strip())
    return " ".join(parts).strip()
