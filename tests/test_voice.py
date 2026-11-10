import os
from fastapi.testclient import TestClient
from api.app import app
from core.auth import issue_token


def _setup_cred():
    os.environ["PAT_MASTER_KEY"] = "u9v2w3x4y5z6A7B8C9D0E1F2G3H4I5J6K7L8M9N0O1P="
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    os.environ["PAT_MASTER_KEY"] = key
    from storage.credentials import CredentialStore
    v = __import__("api.routers.voice", fromlist=["_db"])
    cs = CredentialStore(db=v._db, tenant_id="t1", user_id="u1")
    cs.save("openai", "sk-test")
    return key


def test_auth_failure():
    c = TestClient(app)
    with c.websocket_connect("/voice/session") as ws:
        ws.send_json({"type": "auth", "token": "bad"})
        try:
            ws.receive_json()
        except Exception:
            pass


def test_auth_success_and_echo():
    _setup_cred()
    import unittest.mock as m
    with m.patch("api.routers.voice.transcribe", return_value="hi"), m.patch("api.routers.voice.synthesize", new=m.AsyncMock(return_value=b"\x01\x02")):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        with c.websocket_connect("/voice/session") as ws:
            ws.send_json({"type": "auth", "token": tok})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
            assert ws.receive_json()["type"] == "state"
            ws.send_bytes(b"\x01\x02")
            ws.send_json({"type": "stop"})
            assert ws.receive_json()["type"] == "state"
            tr = ws.receive_json()
            assert tr["type"] == "transcript"
            at = ws.receive_json()
            assert at["type"] == "assistant_text"
            assert ws.receive_json()["type"] == "tts_start"
            tts = ws.receive_bytes()
            assert tts == b"\x01\x02"
            assert ws.receive_json()["type"] == "tts_end"
            data = ws.receive_bytes()
            assert data == b"\x01\x02"
            assert ws.receive_json()["type"] == "audio_end"
            assert ws.receive_json()["type"] == "state"
            ws.send_json({"type": "end"})


def test_asr_transcript_event():
    _setup_cred()
    import unittest.mock as m
    with m.patch("api.routers.voice.transcribe", return_value="recognized speech"), m.patch("api.routers.voice.synthesize", new=m.AsyncMock(return_value=b"\x01\x02")):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        with c.websocket_connect("/voice/session") as ws:
            ws.send_json({"type": "auth", "token": tok})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
            assert ws.receive_json()["type"] == "state"
            ws.send_bytes(b"\x01\x02")
            ws.send_json({"type": "stop"})
            assert ws.receive_json()["type"] == "state"
            tr = ws.receive_json()
            assert tr["type"] == "transcript"
            at = ws.receive_json()
            assert at["type"] == "assistant_text"
            ws.send_json({"type": "end"})


def test_frame_too_large():
    c = TestClient(app)
    with c.websocket_connect("/voice/session") as ws:
        ws.send_json({"type": "auth", "token": issue_token("u1", "t1", "user", 3600)})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
        assert ws.receive_json()["type"] == "state"
        try:
            ws.send_bytes(b"\x00" * (2 * 1024 * 1024 + 1))
            msg = ws.receive_json()
            assert msg["type"] == "error"
        except Exception:
            pass


def test_chunk_count_limit():
    c = TestClient(app)
    with c.websocket_connect("/voice/session") as ws:
        ws.send_json({"type": "auth", "token": issue_token("u1", "t1", "user", 3600)})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
        assert ws.receive_json()["type"] == "state"
        for _ in range(500):
            ws.send_bytes(b"\x01")
        try:
            ws.send_bytes(b"\x01")
            msg = ws.receive_json()
            assert msg["type"] == "error"
        except Exception:
            pass


def test_turn_id_propagation():
    _setup_cred()
    import unittest.mock as m
    gate = __import__("asyncio").Event()
    async def slow_synth(text, key):
        await gate.wait()
        return b"\x01\x02"
    with m.patch("api.routers.voice.transcribe", return_value="hi"), m.patch("api.routers.voice.synthesize", new=m.AsyncMock(side_effect=slow_synth)):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        with c.websocket_connect("/voice/session") as ws:
            ws.send_json({"type": "auth", "token": tok})
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
            st = ws.receive_json()
            assert st["type"] == "state"
            tid = st["turn_id"]
            assert tid
            ws.send_bytes(b"\x01\x02")
            ws.send_json({"type": "stop"})
            assert ws.receive_json()["type"] == "state"  # processing
            tr = ws.receive_json()
            assert tr["type"] == "transcript" and tr["turn_id"] == tid
            at = ws.receive_json()
            assert at["type"] == "assistant_text" and at["turn_id"] == tid
            ts = ws.receive_json()
            assert ts["type"] == "tts_start" and ts["turn_id"] == tid
            # interrupt
            ws.send_json({"type": "interrupt"})
            # cancelled event
            cancelled = ws.receive_json()
            assert cancelled["type"] == "cancelled" and cancelled["turn_id"] == tid
            gate.set()
            ws.send_json({"type": "end"})


def test_interrupt_during_tts():
    _setup_cred()
    import unittest.mock as m, asyncio
    gate = asyncio.Event()
    async def slow_synth(text, key):
        await gate.wait()
        return b"\x01\x02"
    with m.patch("api.routers.voice.transcribe", return_value="hi"), m.patch("api.routers.voice.synthesize", new=m.AsyncMock(side_effect=slow_synth)):
        c = TestClient(app)
        tok = issue_token("u1", "t1", "user", 3600)
        with c.websocket_connect("/voice/session") as ws:
            ws.send_json({"type": "auth", "token": tok})
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "start", "mime_type": "audio/webm;codecs=opus", "agent_id": "communications"})
            assert ws.receive_json()["type"] == "state"
            ws.send_bytes(b"\x01\x02")
            ws.send_json({"type": "stop"})
            assert ws.receive_json()["type"] == "state"  # processing
            assert ws.receive_json()["type"] == "transcript"
            assert ws.receive_json()["type"] == "assistant_text"
            assert ws.receive_json()["type"] == "tts_start"
            ws.send_json({"type": "interrupt"})
            ce = ws.receive_json()
            assert ce["type"] == "cancelled"
            gate.set()
            ws.send_json({"type": "end"})
