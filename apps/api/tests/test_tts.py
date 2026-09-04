import base64
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import tts
from apps.api.main import app


@pytest.fixture
def voices_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(tts, "VOICES_DIR", tmp_path)
    tts._load_voice.cache_clear()
    return tmp_path


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_list_voices_is_empty_without_files(voices_dir: Path) -> None:
    async with await _client() as client:
        response = await client.get("/tts/voices")

    assert response.status_code == 200
    assert response.json() == {"voices": []}


@pytest.mark.anyio
async def test_list_voices_reads_config_metadata(voices_dir: Path) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")
    (voices_dir / "en_US-amy-medium.onnx.json").write_text(
        json.dumps({"num_speakers": 904, "language": {"code": "en_US"}, "audio": {"quality": "high"}})
    )

    async with await _client() as client:
        response = await client.get("/tts/voices")

    assert response.json() == {
        "voices": [
            {
                "id": "en_US-amy-medium",
                "name": "Amy",
                "language": "en_US",
                "quality": "high",
                "speakers": 904,
            }
        ]
    }


@pytest.mark.anyio
async def test_list_voices_falls_back_to_the_id_when_config_is_unreadable(voices_dir: Path) -> None:
    (voices_dir / "fr_FR-siwis-medium.onnx").write_bytes(b"")
    (voices_dir / "fr_FR-siwis-medium.onnx.json").write_text("not json")

    async with await _client() as client:
        response = await client.get("/tts/voices")

    assert response.json()["voices"] == [
        {
            "id": "fr_FR-siwis-medium",
            "name": "Siwis",
            "language": "fr_FR",
            "quality": "medium",
            "speakers": 1,
        }
    ]


@pytest.mark.anyio
async def test_speak_rejects_speaker_beyond_the_voice(voices_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")
    (voices_dir / "en_US-amy-medium.onnx.json").write_text(json.dumps({"num_speakers": 2}))
    monkeypatch.setattr(tts, "_load_voice", lambda voice_id: SimpleNamespace(config=SimpleNamespace(sample_rate=22050)))

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi", "speaker": 5})

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


@pytest.mark.anyio
async def test_speak_passes_speaker_to_piper(voices_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (voices_dir / "en_US-libritts-high.onnx").write_bytes(b"")
    (voices_dir / "en_US-libritts-high.onnx.json").write_text(json.dumps({"num_speakers": 904}))
    captured = {}

    class FakeVoice:
        config = SimpleNamespace(sample_rate=22050)

        def synthesize_wav(self, text, wav_file, syn_config=None, include_alignments=False):
            captured["speaker_id"] = syn_config.speaker_id
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x01")

    monkeypatch.setattr(tts, "_load_voice", lambda voice_id: FakeVoice())

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi", "speaker": 42})

    assert response.status_code == 200
    assert captured["speaker_id"] == 42


@pytest.mark.anyio
async def test_speak_reports_a_corrupt_model_file(voices_dir: Path) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"truncated download")
    (voices_dir / "en_US-amy-medium.onnx.json").write_text(json.dumps({"num_speakers": 1}))

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi"})

    assert response.status_code == 500
    assert "incomplete or corrupt" in response.json()["detail"]


@pytest.mark.anyio
async def test_speak_without_voices_reports_unavailable(voices_dir: Path) -> None:
    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hello"})

    assert response.status_code == 503
    assert "No Piper voices found" in response.json()["detail"]


@pytest.mark.anyio
async def test_speak_rejects_unknown_voice(voices_dir: Path) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi", "voice": "nope"})

    assert response.status_code == 404


@pytest.mark.anyio
async def test_speak_applies_speed_as_inverse_length_scale(voices_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")
    captured = {}

    class FakeVoice:
        config = SimpleNamespace(sample_rate=22050)

        def synthesize_wav(self, text, wav_file, syn_config=None, include_alignments=False):
            captured["length_scale"] = syn_config.length_scale
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x01")

    monkeypatch.setattr(tts, "_load_voice", lambda voice_id: FakeVoice())

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi", "speed": 2.0})

    assert response.status_code == 200
    assert captured["length_scale"] == 0.5


@pytest.mark.anyio
async def test_speak_rejects_out_of_range_speed(voices_dir: Path) -> None:
    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hi", "speed": 9.0})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_speak_rejects_empty_text(voices_dir: Path) -> None:
    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": ""})

    assert response.status_code == 422


@pytest.mark.anyio
async def test_speak_returns_audio_with_a_viseme_timeline(
    voices_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")

    class FakeVoice:
        config = SimpleNamespace(sample_rate=22050)

        def synthesize_wav(self, text, wav_file, syn_config=None, include_alignments=False):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x01" * len(text))
            return [SimpleNamespace(phoneme="ɑ", num_samples=2205)]

    monkeypatch.setattr(tts, "_load_voice", lambda voice_id: FakeVoice())

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["sample_rate"] == 22050
    assert body["visemes"] == [{"viseme": "aa", "weight": 1.0, "start": 0.0, "end": 0.1}]

    with wave.open(io.BytesIO(base64.b64decode(body["audio"])), "rb") as wav_file:
        assert wav_file.getframerate() == 22050
        assert wav_file.getnframes() == len("hello")


@pytest.mark.anyio
async def test_speak_returns_an_empty_timeline_without_alignments(
    voices_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (voices_dir / "en_US-amy-medium.onnx").write_bytes(b"")

    class FakeVoice:
        config = SimpleNamespace(sample_rate=22050)

        def synthesize_wav(self, text, wav_file, syn_config=None, include_alignments=False):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x01")
            return None

    monkeypatch.setattr(tts, "_load_voice", lambda voice_id: FakeVoice())

    async with await _client() as client:
        response = await client.post("/tts/speak", json={"text": "hello"})

    assert response.status_code == 200
    assert response.json()["visemes"] == []
