"""Local neural text-to-speech backed by Piper voice files.

Voices are ``.onnx`` model files (with a sibling ``.onnx.json`` config) placed in the
directory named by ``PIPER_VOICES_DIR``. Download them from
https://huggingface.co/rhasspy/piper-voices or train your own.
"""

from __future__ import annotations

import base64
import io
import json
import os
import wave
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.visemes import to_visemes

VOICES_DIR = Path(os.getenv("PIPER_VOICES_DIR", "apps/api/voices"))
# Long enough for a full spoken reply; Piper synthesizes sentence by sentence internally.
MAX_TTS_CHARS = 6000

router = APIRouter(prefix="/tts", tags=["tts"])


class Voice(BaseModel):
    id: str
    name: str
    language: str
    quality: str
    speakers: int = 1


class VoicesResponse(BaseModel):
    voices: list[Voice]


class VisemeFrame(BaseModel):
    viseme: str
    weight: float
    start: float
    end: float


class SpeakResponse(BaseModel):
    """WAV audio as base64, with the mouth shapes that drive the avatar's lipsync."""

    audio: str
    sample_rate: int
    visemes: list[VisemeFrame]


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    voice: str | None = Field(default=None, max_length=128)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    speaker: int = Field(default=0, ge=0, le=1000)


def voice_files() -> dict[str, Path]:
    """Map voice id to its model path, ignoring the sibling ``.onnx.json`` configs."""
    if not VOICES_DIR.is_dir():
        return {}
    return {path.stem: path for path in sorted(VOICES_DIR.glob("*.onnx"))}


def _describe(voice_id: str, path: Path) -> Voice:
    """Read a voice's metadata, falling back to the ``<lang>-<name>-<quality>`` id convention."""
    parts = voice_id.split("-")
    language = parts[0] if len(parts) > 1 else "unknown"
    name = parts[1].replace("_", " ").title() if len(parts) > 2 else voice_id
    quality = parts[-1] if len(parts) > 2 else "unknown"
    speakers = 1

    try:
        config = json.loads(path.with_suffix(".onnx.json").read_text())
    except (OSError, ValueError):
        return Voice(id=voice_id, name=name, language=language, quality=quality, speakers=speakers)

    speakers = max(1, int(config.get("num_speakers", 1)))
    spoken = config.get("language", {})
    if isinstance(spoken, dict) and spoken.get("code"):
        language = str(spoken["code"])
    quality = str(config.get("audio", {}).get("quality", quality))
    return Voice(id=voice_id, name=name, language=language, quality=quality, speakers=speakers)


@lru_cache(maxsize=4)
def _load_voice(voice_id: str):
    """Load and cache a Piper voice. Each model costs ~100MB of RSS once loaded."""
    path = voice_files().get(voice_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown voice '{voice_id}'.")

    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="piper-tts is not installed. Run: pip install -r apps/api/requirements.txt",
        ) from exc

    try:
        # Alignments must be enabled at load time; they add the phoneme timings lipsync needs.
        return PiperVoice.load(path, include_alignments=True)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Voice '{voice_id}' could not be loaded; the model file is likely incomplete or corrupt. "
                f"Re-download {path.name} and its .onnx.json config."
            ),
        ) from exc


def _synthesis_config(speed: float, speaker: int):
    """Piper stretches audio by ``length_scale``, so it is the inverse of playback speed."""
    from piper import SynthesisConfig

    return SynthesisConfig(length_scale=1.0 / speed, speaker_id=speaker or None)


@router.get("/voices", response_model=VoicesResponse)
def list_voices() -> VoicesResponse:
    return VoicesResponse(voices=[_describe(voice_id, path) for voice_id, path in voice_files().items()])


@router.post("/speak", response_model=SpeakResponse)
def speak(request: SpeakRequest) -> SpeakResponse:
    available = voice_files()
    if not available:
        raise HTTPException(
            status_code=503,
            detail=f"No Piper voices found in {VOICES_DIR}. Add a .onnx voice file to enable server speech.",
        )

    voice_id = request.voice or next(iter(available))
    voice = _load_voice(voice_id)

    speakers = _describe(voice_id, available[voice_id]).speakers
    if request.speaker >= speakers:
        raise HTTPException(
            status_code=400,
            detail=f"Voice '{voice_id}' has {speakers} speaker(s); speaker {request.speaker} does not exist.",
        )

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        alignments = voice.synthesize_wav(
            request.text,
            wav_file,
            syn_config=_synthesis_config(request.speed, request.speaker),
            include_alignments=True,
        )

    sample_rate = voice.config.sample_rate
    visemes = [VisemeFrame(**frame._asdict()) for frame in to_visemes(alignments or [], sample_rate)]
    return SpeakResponse(
        audio=base64.b64encode(buffer.getvalue()).decode("ascii"),
        sample_rate=sample_rate,
        visemes=visemes,
    )
