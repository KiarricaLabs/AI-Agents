import os
from unittest.mock import patch, MagicMock
import httpx

from core.voice_asr import transcribe


def _mock_resp(status=200, json_data=None, raise_exc=None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = json_data or {}
    if raise_exc:
        m.raise_for_status.side_effect = raise_exc
    return m


def test_success():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(200, {"text": "hello world"})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        out = transcribe(b"\x00\x01", "audio/webm;codecs=opus", "sk-test")
    assert out == "hello world"


def test_webm_mime():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(200, {"text": "hi"})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        out = transcribe(b"\x00", "audio/webm", "sk-test")
    assert out == "hi"


def test_mp4_mime():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(200, {"text": "hi"})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        out = transcribe(b"\x00", "audio/mp4", "sk-test")
    assert out == "hi"


def test_unsupported_mime():
    try:
        transcribe(b"\x00", "audio/ogg;codecs=opus", "sk-test")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_empty_audio():
    try:
        transcribe(b"", "audio/webm;codecs=opus", "sk-test")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_missing_key():
    try:
        transcribe(b"\x00", "audio/webm;codecs=opus", "")
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")


def test_auth_failure():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(401, {})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        try:
            transcribe(b"\x00", "audio/webm;codecs=opus", "sk-test")
        except RuntimeError as e:
            assert "invalid api key" in str(e)
            return
    raise AssertionError("expected RuntimeError")


def test_rate_limit():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(429, {})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        try:
            transcribe(b"\x00", "audio/webm;codecs=opus", "sk-test")
        except RuntimeError as e:
            assert "rate limited" in str(e)
            return
    raise AssertionError("expected RuntimeError")


def test_server_error():
    fake = MagicMock()
    fake.__enter__.return_value.post.return_value = _mock_resp(500, {})
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        try:
            transcribe(b"\x00", "audio/webm;codecs=opus", "sk-test")
        except RuntimeError as e:
            assert "provider error" in str(e)
            return
    raise AssertionError("expected RuntimeError")


def test_timeout():
    fake = MagicMock()
    fake.__enter__.return_value.post.side_effect = httpx.TimeoutException("t")
    with patch("core.voice_asr.httpx.Client", return_value=fake):
        try:
            transcribe(b"\x00", "audio/webm;codecs=opus", "sk-test")
        except RuntimeError as e:
            assert "timeout" in str(e)
            return
    raise AssertionError("expected RuntimeError")
