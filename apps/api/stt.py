"""Local speech-to-text with Whisper.

The browser's own recognition is a cloud service: Chromium sends the audio to Google. That
undercuts a stack whose whole point is that inference stays where you put it, so this
transcribes on the same machine as everything else.

The model is downloaded on first use and cached; ``WHISPER_MODEL`` chooses which.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
MAX_AUDIO_BYTES = int(os.getenv("STT_MAX_BYTES", str(25 * 1024 * 1024)))

router = APIRouter(prefix="/stt", tags=["stt"])


class Transcription(BaseModel):
    text: str
    language: str


@lru_cache(maxsize=1)
def _model():
    """Load and cache the Whisper model. The first call downloads it."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="faster-whisper is not installed. Run: pip install -r apps/api/requirements.txt",
        ) from exc

    try:
        return WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Whisper model '{MODEL_NAME}' could not be loaded: {exc}",
        ) from exc


def is_available() -> bool:
    """Whether the server can transcribe, without paying to load the model."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


@router.get("/status")
def status() -> dict[str, object]:
    return {"available": is_available(), "model": MODEL_NAME}


@router.post("/transcribe", response_model=Transcription)
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> Transcription:
    """Transcribe recorded audio.

    Args:
        audio: The recording, in any container PyAV can decode (webm, ogg, wav, mp3).
        language: BCP-47 tag of the expected language; Whisper detects it when omitted.
    """
    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=422, detail="The audio file is empty.")
    if len(payload) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Recording is larger than {MAX_AUDIO_BYTES // (1024 * 1024)}MB.",
        )

    model = _model()
    # Whisper wants a bare language code; the browser sends a full tag like "fr-FR".
    code = language.split("-")[0].lower() if language else None

    try:
        segments, info = model.transcribe(io.BytesIO(payload), language=code, vad_filter=True)
        text = "".join(segment.text for segment in segments).strip()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode the audio: {exc}") from exc

    # getattr's default only applies when the attribute is missing, not when it is None.
    detected = getattr(info, "language", None) or code or "unknown"
    return Transcription(text=text, language=detected)
