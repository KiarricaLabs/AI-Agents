"""WebSocket voice transport (V1.1-V1.2.4.2)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.auth import verify_token
from core.voice_asr import transcribe
from core.voice_tts import synthesize
from core.runtime import build_runtime, load_registry
from storage.credentials import CredentialStore
from storage.database import Database
from config.settings import DB_PATH, DEFAULT_TENANT

_db = Database(path=DB_PATH, tenant_id=DEFAULT_TENANT)

router = APIRouter()

MAX_BYTES = 5 * 1024 * 1024
MAX_DURATION = 120.0
MAX_CHUNKS = 500
AUTH_TIMEOUT = 10.0
IDLE_TIMEOUT = 60.0


class VoiceSession:
    def __init__(self, session_id: str, tenant_id: str, user_id: str):
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.buffer = bytearray()
        self.chunk_count = 0
        self.started_at = time.monotonic()
        self.last_activity = time.monotonic()
        self.mime_type = "audio/webm;codecs=opus"
        self.state = "authed"
        self.agent_id = None
        self.thread_id = None
        self.turn_id = None
        self.interrupted = False
        self.turn_task = None
        self.tts_task = None
        self.tts_turn_id = None
        self.send_lock = asyncio.Lock()

    async def send(self, ws, payload):
        async with self.send_lock:
            if isinstance(payload, (bytes, bytearray)):
                await ws.send_bytes(bytes(payload))
            else:
                await ws.send_json(payload)


async def _auth(ws: WebSocket) -> Optional[VoiceSession]:
    try:
        raw = await asyncio.wait_for(ws.receive_json(), timeout=AUTH_TIMEOUT)
    except asyncio.TimeoutError:
        await ws.close(code=1008, reason="auth timeout")
        return None
    if not isinstance(raw, dict) or raw.get("type") != "auth" or not raw.get("token"):
        await ws.close(code=1008, reason="auth required")
        return None
    info = verify_token(str(raw["token"]))
    if not info:
        await ws.close(code=1008, reason="auth failed")
        return None
    tenant_id = info.get("tenant") or info.get("tenant_id")
    user_id = info.get("sub") or info.get("user_id")
    if not tenant_id or not user_id:
        await ws.close(code=1008, reason="auth failed")
        return None
    return VoiceSession(str(uuid.uuid4()), str(tenant_id), str(user_id))


async def _process_turn(session: VoiceSession, ws: WebSocket, buf: bytes, text: str):
    turn_id = session.turn_id
    try:
        if not session.agent_id:
            await session.send(ws, {"type": "error", "code": "missing_agent", "message": "agent_id required", "turn_id": turn_id})
            await ws.close(code=1003, reason="missing agent")
            return
        reg = load_registry()
        manifest = reg.get(session.agent_id) if hasattr(reg, "get") else None
        if not manifest:
            await session.send(ws, {"type": "error", "code": "invalid_agent", "message": "unknown agent", "turn_id": turn_id})
            await ws.close(code=1003, reason="invalid agent")
            return
        thread_id = session.thread_id or str(uuid.uuid4())
        session.thread_id = thread_id
        if session.interrupted:
            await session.send(ws, {"type": "cancelled", "turn_id": turn_id})
            session.state = "idle"
            session.buffer = bytearray()
            await session.send(ws, {"type": "state", "state": "idle", "turn_id": turn_id})
            return
        try:
            orch = build_runtime(_db, session.tenant_id, session.user_id)
            result = orch.dispatch(session.agent_id, text, {"thread_id": thread_id})
        except PermissionError as e:
            await session.send(ws, {"type": "error", "code": "permission_denied", "message": str(e), "turn_id": turn_id})
            await ws.close(code=1008, reason="permission denied")
            return
        except Exception as e:
            await session.send(ws, {"type": "error", "code": "runtime_failed", "message": str(e), "turn_id": turn_id})
            await ws.close(code=1011, reason="runtime failed")
            return
        if session.interrupted or session.turn_id != turn_id:
            await session.send(ws, {"type": "cancelled", "turn_id": turn_id})
            session.state = "idle"
            session.buffer = bytearray()
            await session.send(ws, {"type": "state", "state": "idle", "turn_id": turn_id})
            return
        reply = result.get("reply") if isinstance(result, dict) else str(result)
        if reply is None:
            reply = str(result)
        try:
            mem = orch.memory
            mem.get_or_create_thread(session.user_id, thread_id, session.agent_id, text)
            mem.add_conversation_pair(session.user_id, thread_id, text, reply, turn_id=turn_id)
        except Exception:
            pass
        if session.interrupted or session.turn_id != turn_id:
            await session.send(ws, {"type": "cancelled", "turn_id": turn_id})
            session.state = "idle"
            session.buffer = bytearray()
            await session.send(ws, {"type": "state", "state": "idle", "turn_id": turn_id})
            return
        await session.send(ws, {"type": "assistant_text", "text": reply, "agent": session.agent_id, "thread_id": thread_id, "turn_id": turn_id})

        # TTS
        session.state = "speaking"
        await session.send(ws, {"type": "tts_start", "turn_id": turn_id})
        audio = None
        try:
            cs = CredentialStore(db=_db, tenant_id=session.tenant_id, user_id=session.user_id)
            api_key = cs.retrieve("openai")
            session.tts_turn_id = turn_id
            session.tts_task = asyncio.create_task(synthesize(reply, api_key))
            audio = await session.tts_task
        except asyncio.CancelledError:
            session.tts_task = None
            await session.send(ws, {"type": "cancelled", "turn_id": turn_id})
            session.state = "idle"
            session.buffer = bytearray()
            await session.send(ws, {"type": "state", "state": "idle", "turn_id": turn_id})
            return
        except Exception as e:
            session.tts_task = None
            await session.send(ws, {"type": "tts_error", "code": "tts_failed", "message": str(e), "turn_id": turn_id})
        else:
            session.tts_task = None
            if session.interrupted or session.turn_id != turn_id:
                await session.send(ws, {"type": "cancelled", "turn_id": turn_id})
            else:
                for i in range(0, len(audio), 4096):
                    if session.interrupted or session.turn_id != turn_id:
                        break
                    await session.send(ws, audio[i:i + 4096])
                if not session.interrupted and session.turn_id == turn_id:
                    await session.send(ws, {"type": "tts_end", "mime_type": "audio/mpeg", "turn_id": turn_id})
        # echo
        if not session.interrupted and session.turn_id == turn_id:
            for i in range(0, len(buf), 4096):
                if session.interrupted or session.turn_id != turn_id:
                    break
                await session.send(ws, buf[i:i + 4096])
            if not session.interrupted and session.turn_id == turn_id:
                await session.send(ws, {"type": "audio_end", "mime_type": session.mime_type, "turn_id": turn_id})
        session.state = "idle"
        session.buffer = bytearray()
        await session.send(ws, {"type": "state", "state": "idle", "turn_id": turn_id})
    except Exception as e:
        await session.send(ws, {"type": "error", "code": "turn_failed", "message": str(e), "turn_id": session.turn_id})
    finally:
        session.turn_task = None


@router.websocket("/voice/session")
async def voice_session(ws: WebSocket):
    await ws.accept()
    session = await _auth(ws)
    if session is None:
        return
    await session.send(ws, {"type": "ready", "session_id": session.session_id})
    try:
        while True:
            if time.monotonic() - session.last_activity > IDLE_TIMEOUT:
                await ws.close(code=1001, reason="idle timeout")
                return
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            session.last_activity = time.monotonic()

            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                except Exception:
                    await session.send(ws, {"type": "error", "code": "bad_json", "message": "invalid json"})
                    continue
                if not isinstance(data, dict):
                    await session.send(ws, {"type": "error", "code": "bad_msg", "message": "expected object"})
                    continue
                t = data.get("type")
                if t == "start":
                    if session.state in ("processing", "transcribing", "responding") or (session.turn_task and not session.turn_task.done()):
                        await session.send(ws, {"type": "error", "code": "busy", "message": "session busy", "turn_id": session.turn_id})
                        continue
                    session.turn_id = str(uuid.uuid4())
                    session.interrupted = False
                    session.state = "recording"
                    session.buffer = bytearray()
                    session.chunk_count = 0
                    session.started_at = time.monotonic()
                    if data.get("mime_type"):
                        session.mime_type = str(data["mime_type"])
                    if data.get("agent_id"):
                        session.agent_id = str(data["agent_id"])
                    if data.get("thread_id"):
                        session.thread_id = str(data["thread_id"])
                    await session.send(ws, {"type": "state", "state": "recording", "turn_id": session.turn_id})
                elif t == "interrupt":
                    session.interrupted = True
                    if session.tts_task and not session.tts_task.done() and session.tts_turn_id == session.turn_id:
                        session.tts_task.cancel()
                    await session.send(ws, {"type": "cancelled", "turn_id": session.turn_id})
                elif t == "stop":
                    if session.state != "recording":
                        await session.send(ws, {"type": "error", "code": "invalid_state", "message": "not recording", "turn_id": session.turn_id})
                        continue
                    session.state = "processing"
                    await session.send(ws, {"type": "state", "state": "processing", "turn_id": session.turn_id})
                    buf = bytes(session.buffer)
                    # ASR inline (blocking, run in thread)
                    try:
                        cs = CredentialStore(db=_db, tenant_id=session.tenant_id, user_id=session.user_id)
                        api_key = cs.retrieve("openai")
                    except Exception:
                        await session.send(ws, {"type": "error", "code": "missing_credentials", "message": "missing openai credential", "turn_id": session.turn_id})
                        await ws.close(code=1011, reason="missing credentials")
                        return
                    try:
                        text = await asyncio.to_thread(transcribe, buf, session.mime_type, api_key)
                    except Exception as e:
                        await session.send(ws, {"type": "error", "code": "asr_failed", "message": str(e), "turn_id": session.turn_id})
                        await ws.close(code=1011, reason="asr failed")
                        return
                    await session.send(ws, {"type": "transcript", "text": text, "turn_id": session.turn_id})
                    session.turn_task = asyncio.create_task(_process_turn(session, ws, buf, text))
                elif t == "end":
                    await ws.close(code=1000, reason="client end")
                    return
                else:
                    await session.send(ws, {"type": "error", "code": "unknown", "message": f"unknown type {t}", "turn_id": session.turn_id})
            elif "bytes" in msg and msg["bytes"] is not None:
                if session.state != "recording":
                    continue
                chunk = msg["bytes"]
                if not chunk:
                    continue
                if len(chunk) > 2 * 1024 * 1024:
                    await session.send(ws, {"type": "error", "code": "limit_exceeded", "message": "frame too large", "turn_id": session.turn_id})
                    await ws.close(code=1009, reason="frame limit")
                    return
                if session.chunk_count >= MAX_CHUNKS:
                    await session.send(ws, {"type": "error", "code": "limit_exceeded", "message": "too many chunks", "turn_id": session.turn_id})
                    await ws.close(code=1009, reason="chunk limit")
                    return
                if len(session.buffer) + len(chunk) > MAX_BYTES:
                    await session.send(ws, {"type": "error", "code": "limit_exceeded", "message": "audio too large", "turn_id": session.turn_id})
                    await ws.close(code=1009, reason="size limit")
                    return
                if time.monotonic() - session.started_at > MAX_DURATION:
                    await session.send(ws, {"type": "error", "code": "limit_exceeded", "message": "recording too long", "turn_id": session.turn_id})
                    await ws.close(code=1009, reason="duration limit")
                    return
                session.buffer.extend(chunk)
                session.chunk_count += 1
            else:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        if session.turn_task and not session.turn_task.done():
            session.turn_task.cancel()
        if session.tts_task and not session.tts_task.done():
            session.tts_task.cancel()
        session.buffer = bytearray()
