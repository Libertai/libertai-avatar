from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import stt
from apps.api.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def fake_model(monkeypatch: pytest.MonkeyPatch, text: str = "hello there", language: str = "en") -> dict:
    captured: dict = {}

    class FakeModel:
        def transcribe(self, audio, language=None, vad_filter=False):
            captured["language"] = language
            captured["vad_filter"] = vad_filter
            captured["bytes"] = audio.read()
            return ([SimpleNamespace(text=text)], SimpleNamespace(language=language or language))

    monkeypatch.setattr(stt, "_model", lambda: FakeModel())
    return captured


@pytest.mark.anyio
async def test_status_reports_the_model() -> None:
    async with await _client() as client:
        response = await client.get("/stt/status")

    assert response.status_code == 200
    assert response.json()["model"] == stt.MODEL_NAME


@pytest.mark.anyio
async def test_transcribes_uploaded_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = fake_model(monkeypatch)

    async with await _client() as client:
        response = await client.post(
            "/stt/transcribe",
            files={"audio": ("speech.webm", b"fake audio bytes", "audio/webm")},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "hello there"
    assert captured["bytes"] == b"fake audio bytes"


@pytest.mark.anyio
async def test_a_full_language_tag_is_reduced_to_the_code_whisper_wants(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = fake_model(monkeypatch)

    async with await _client() as client:
        await client.post(
            "/stt/transcribe",
            files={"audio": ("speech.webm", b"audio", "audio/webm")},
            data={"language": "fr-FR"},
        )

    assert captured["language"] == "fr"


@pytest.mark.anyio
async def test_without_a_language_whisper_detects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = fake_model(monkeypatch)

    async with await _client() as client:
        await client.post("/stt/transcribe", files={"audio": ("speech.webm", b"audio", "audio/webm")})

    assert captured["language"] is None


@pytest.mark.anyio
async def test_empty_audio_is_rejected() -> None:
    async with await _client() as client:
        response = await client.post("/stt/transcribe", files={"audio": ("speech.webm", b"", "audio/webm")})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_oversized_audio_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt, "MAX_AUDIO_BYTES", 10)

    async with await _client() as client:
        response = await client.post(
            "/stt/transcribe",
            files={"audio": ("speech.webm", b"far too many bytes", "audio/webm")},
        )

    assert response.status_code == 413


@pytest.mark.anyio
async def test_undecodable_audio_reports_why(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenModel:
        def transcribe(self, audio, language=None, vad_filter=False):
            raise ValueError("not an audio stream")

    monkeypatch.setattr(stt, "_model", lambda: BrokenModel())

    async with await _client() as client:
        response = await client.post("/stt/transcribe", files={"audio": ("x.webm", b"junk", "audio/webm")})

    assert response.status_code == 422
    assert "not an audio stream" in response.json()["detail"]
