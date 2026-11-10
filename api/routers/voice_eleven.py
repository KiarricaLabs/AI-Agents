from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json, os
from pathlib import Path

router = APIRouter(prefix="/voice", tags=["voice"])

VOICES = {}
try:
    p = Path("config/elevenlabs_voices.json")
    if p.exists():
        VOICES = json.loads(p.read_text())
except: pass

class SpeakReq(BaseModel):
    agent: str
    text: str

@router.post("/speak")
async def speak(req: SpeakReq):
    from dotenv import load_dotenv
    load_dotenv(".env")
    voice_id = VOICES.get(req.agent) or VOICES.get(req.agent.lower())
    if not voice_id:
        raise HTTPException(status_code=404, detail="no voice for agent")
    try:
        from elevenlabs import ElevenLabs
        client = ElevenLabs()
        audio = client.text_to_speech.convert(text=req.text[:2000], voice_id=voice_id, model_id="eleven_flash_v2_5")
        def gen():
            for chunk in audio:
                yield chunk
        return StreamingResponse(gen(), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
