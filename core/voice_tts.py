"""Text-to-speech helper for V1.2.3/V1.2.4.2 (OpenAI TTS, async)."""
from __future__ import annotations

import httpx

OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"
MODEL = "tts-1"
VOICE = "alloy"
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT = 60.0


async def synthesize(text: str, api_key: str) -> bytes:
    if not text or not text.strip():
        raise ValueError("empty text")
    if not api_key:
        raise RuntimeError("missing api key")
    payload = {"model": MODEL, "input": text, "voice": VOICE, "response_format": "mp3"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            async with client.stream("POST", OPENAI_SPEECH_URL, headers=headers, json=payload) as resp:
                if resp.status_code == 401:
                    raise RuntimeError("invalid api key")
                if resp.status_code == 429:
                    raise RuntimeError("rate limited")
                if resp.status_code >= 500:
                    raise RuntimeError("provider error")
                if resp.status_code >= 400:
                    raise RuntimeError(f"tts failed: {resp.status_code}")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    if len(buf) + len(chunk) > MAX_BYTES:
                        raise RuntimeError("audio too large")
                    buf.extend(chunk)
                if not buf:
                    raise RuntimeError("empty audio")
                return bytes(buf)
    except httpx.TimeoutException as e:
        raise RuntimeError("tts timeout") from e
    except httpx.HTTPError as e:
        raise RuntimeError("tts request failed") from e
