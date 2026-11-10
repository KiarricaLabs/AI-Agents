import { useEffect, useRef, useState } from "react";
import { VoiceIndicator } from "./VoiceIndicator";

interface Props { value: string; onChange: (v: string) => void; onSend: () => void; placeholder: string; disabled?: boolean; }

export function Composer({ value, onChange, onSend, placeholder, disabled }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [listening, setListening] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const recogRef = useRef<any>(null);
  const timerRef = useRef<any>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => { if (ref.current) { ref.current.style.height="auto"; ref.current.style.height=Math.min(ref.current.scrollHeight,160)+"px"; } }, [value]);

  const toggleVoice = async () => {
    const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { setVoiceError("Voice not supported."); return; }
    if (disabled) return;
    if (listening && recogRef.current) { recogRef.current.stop(); setListening(false); clearInterval(timerRef.current); analyserRef.current=null; audioCtxRef.current?.close(); return; }
    setVoiceError("");
    let stream: MediaStream | null = null;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { setVoiceError("Microphone permission denied."); return; }
    // setup analyser for indicator
    try { const ctx = new (window.AudioContext || (window as any).webkitAudioContext)(); audioCtxRef.current=ctx; const src=ctx.createMediaStreamSource(stream); const analyser=ctx.createAnalyser(); analyser.fftSize=64; src.connect(analyser); analyserRef.current=analyser; } catch {}
    const recog = new SR();
    recog.lang="en-US"; recog.interimResults=false;
    recog.onresult=(e:any)=>{ onChange(value?value+" "+e.results[0][0].transcript:e.results[0][0].transcript); setListening(false); clearInterval(timerRef.current); stream?.getTracks().forEach(t=>t.stop()); analyserRef.current=null; };
    recog.onerror=(e:any)=>{ setVoiceError(e?.error||"Mic error"); setListening(false); clearInterval(timerRef.current); stream?.getTracks().forEach(t=>t.stop()); };
    recog.onend=()=>{ setListening(false); clearInterval(timerRef.current); stream?.getTracks().forEach(t=>t.stop()); };
    recogRef.current=recog;
    try { recog.start(); setListening(true); setElapsed(0); timerRef.current=setInterval(()=>setElapsed(s=>s+1),1000); } catch { setVoiceError("Mic denied."); }
  };

  return (
    <div className="composer-wrap">
      <div className="composer">
        <button type="button" className={`composer__mic ${listening?"composer__mic--active":""}`} onClick={toggleVoice} aria-label="Voice" disabled={disabled}>{listening?"■":"🎤"}</button>
        <textarea ref={ref} data-testid="team-chat-input" className="composer__input" value={value} onChange={e=>onChange(e.target.value)} onKeyDown={e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); if(!disabled&&value.trim()) onSend(); } }} placeholder={placeholder} rows={1} disabled={disabled} />
        <button type="button" className="composer__send" onClick={onSend} disabled={disabled||!value.trim()} aria-label="Send">↑</button>
      </div>
      {listening && <div style={{display:"flex",alignItems:"center",gap:8}}><VoiceIndicator active={listening} analyser={analyserRef.current} /><span style={{fontSize:11,color:"var(--accent)"}}>Listening… {elapsed}s</span></div>}
      {voiceError && <div className="composer__error">{voiceError}</div>}
    </div>
  );
}
