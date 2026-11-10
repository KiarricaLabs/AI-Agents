"""Speech-to-text helper for V1.2.1 (OpenAI Whisper)."""
from __future__ import annotations

import httpx

OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "whisper-1"
TIMEOUT = 30.0

MIME_TO_EXT = {
    "audio/webm;codecs=opus": "webm",
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/mp4;codecs=mp4a.40.2": "mp4",
}


def transcribe(audio_bytes: bytes, mime_type: str, api_key: str) -> str:
    ext = MIME_TO_EXT.get(mime_type)
    if ext is None:
        raise ValueError(f"unsupported mime type: {mime_type}")
    if not audio_bytes:
        raise ValueError("empty audio")
    if not api_key:
        raise RuntimeError("missing api key")
    filename = f"audio.{ext}"
    files = {"file": (filename, audio_bytes, mime_type)}
    data = {"model": MODEL}
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(OPENAI_TRANSCRIPTION_URL, headers=headers, data=data, files=files)
    except httpx.TimeoutException as e:
        raise RuntimeError("transcription timeout") from e
    except httpx.HTTPError as e:
        raise RuntimeError("transcription request failed") from e
    if resp.status_code == 401:
        raise RuntimeError("invalid api key")
    if resp.status_code == 429:
        raise RuntimeError("rate limited")
    if resp.status_code >= 500:
        raise RuntimeError("provider error")
    if resp.status_code >= 400:
        raise RuntimeError(f"transcription failed: {resp.status_code}")
    payload = resp.json()
    return str(payload.get("text", "")).strip()
