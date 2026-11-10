import os, asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from core.voice_tts import synthesize

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)

def test_success():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 200
        async def gen():
            yield b"\xff\xfb"
        stream_cm.aiter_bytes.return_value = gen()
        out = asyncio.run(synthesize("hello", "sk-test"))
    assert out == b"\xff\xfb"

def test_empty_text():
    try:
        asyncio.run(synthesize("", "sk-test"))
    except ValueError:
        return
    raise AssertionError("expected ValueError")

def test_missing_key():
    try:
        asyncio.run(synthesize("hi", ""))
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")

def test_auth_failure():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 401
        async def gen():
            return
            yield b""
        stream_cm.aiter_bytes.return_value = gen()
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "invalid api key" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_rate_limit():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 429
        async def gen():
            return
            yield b""
        stream_cm.aiter_bytes.return_value = gen()
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "rate limited" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_server_error():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 500
        async def gen():
            return
            yield b""
        stream_cm.aiter_bytes.return_value = gen()
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "provider error" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_timeout():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        inst.stream.side_effect = httpx.TimeoutException("t")
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "timeout" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_empty_audio():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 200
        async def gen():
            return
            yield b""
        stream_cm.aiter_bytes.return_value = gen()
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "empty audio" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_oversized():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 200
        async def gen():
            yield b"\x00" * (10 * 1024 * 1024 + 1)
        stream_cm.aiter_bytes.return_value = gen()
        try:
            asyncio.run(synthesize("hi", "sk-test"))
        except RuntimeError as e:
            assert "too large" in str(e)
            return
    raise AssertionError("expected RuntimeError")

def test_request_params():
    with patch("core.voice_tts.httpx.AsyncClient") as C:
        inst = C.return_value
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=None)
        stream_cm = MagicMock()
        inst.stream.return_value.__aenter__ = AsyncMock(return_value=stream_cm)
        inst.stream.return_value.__aexit__ = AsyncMock(return_value=None)
        stream_cm.status_code = 200
        async def gen():
            yield b"\xff\xfb"
        stream_cm.aiter_bytes.return_value = gen()
        out = asyncio.run(synthesize("hello", "sk-test"))
    assert out == b"\xff\xfb"
    call = inst.stream.call_args
    assert call.args[0] == "POST"
    assert call.args[1] == "https://api.openai.com/v1/audio/speech"
    assert call.kwargs["json"]["model"] == "tts-1"
    assert call.kwargs["json"]["voice"] == "alloy"
    assert call.kwargs["json"]["response_format"] == "mp3"
    assert call.kwargs["json"]["input"] == "hello"
    assert "Bearer sk-test" in call.kwargs["headers"]["Authorization"]
