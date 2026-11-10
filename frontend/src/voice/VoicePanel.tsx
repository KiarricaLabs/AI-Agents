import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8001";
const WS = API.replace(/^http/, "ws") + "/voice/session";

function pickMime(): string | null {
  const cands = ["audio/webm;codecs=opus", "audio/mp4"];
  for (const c of cands) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  }
  return null;
}

export function VoicePanel() {
  const [status, setStatus] = useState("idle");
  const [agentId, setAgentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const ttsChunksRef = useRef<Blob[]>([]);
  const ttsActiveRef = useRef(false);
  const turnIdRef = useRef<string | null>(null);
  const ttsUrlRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const token = localStorage.getItem("pat_token") || "";

  function connect() {
    setStatus("connecting");
    setError(null);
    const ws = new WebSocket(WS);
    wsRef.current = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token }));
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const msg = JSON.parse(ev.data);
        if (msg.turn_id && turnIdRef.current && msg.turn_id !== turnIdRef.current && msg.type !== "ready") {
          return;
        }
        if (msg.type === "ready") setStatus("ready");
        else if (msg.type === "state" && msg.turn_id) { turnIdRef.current = msg.turn_id; }
        else if (msg.type === "state") setStatus(msg.state);
        else if (msg.type === "tts_start") { if (msg.turn_id && turnIdRef.current && msg.turn_id !== turnIdRef.current) return; ttsChunksRef.current = []; ttsActiveRef.current = true; }
        else if (msg.type === "tts_end") {
          if (ttsUrlRef.current) { URL.revokeObjectURL(ttsUrlRef.current); ttsUrlRef.current = null; }
          const blob = new Blob(ttsChunksRef.current, { type: msg.mime_type || "audio/mpeg" });
          const url = URL.createObjectURL(blob);
          ttsUrlRef.current = url;
          if (audioRef.current) {
            audioRef.current.src = url;
            audioRef.current.onended = () => { if (ttsUrlRef.current === url) { URL.revokeObjectURL(url); ttsUrlRef.current = null; } };
            audioRef.current.onerror = () => { if (ttsUrlRef.current === url) { URL.revokeObjectURL(url); ttsUrlRef.current = null; } };
            audioRef.current.play().catch(()=>{});
          }
          ttsChunksRef.current = [];
          ttsActiveRef.current = false;
        } else if (msg.type === "tts_error") { setError(msg.message); ttsChunksRef.current = []; }
        else if (msg.type === "audio_end") {
          const blob = new Blob(chunksRef.current, { type: msg.mime_type });
          const url = URL.createObjectURL(blob);
          if (audioRef.current) {
            audioRef.current.src = url;
            audioRef.current.play().catch(() => {});
          }
          chunksRef.current = [];
          setStatus("ready");
        } else if (msg.type === "error") setError(msg.message);
      } else {
        if (ttsActiveRef.current) ttsChunksRef.current.push(new Blob([ev.data]));
        else chunksRef.current.push(new Blob([ev.data]));
      }
    };
    ws.onclose = () => { setStatus("idle"); wsRef.current = null; ttsActiveRef.current = false; ttsChunksRef.current = []; if (ttsUrlRef.current) { URL.revokeObjectURL(ttsUrlRef.current); ttsUrlRef.current = null; } };
    ws.onerror = () => setError("connection error");
  }

  function start() {
    if (status === "speaking" && wsRef.current) { wsRef.current.send(JSON.stringify({ type: "interrupt" })); }
    setError(null);
    const mime = pickMime();
    if (!mime) { setError("unsupported browser"); return; }
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      const rec = new MediaRecorder(stream, { mimeType: mime });
      recRef.current = rec;
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = () => {
        const ws = wsRef.current;
        if (!ws) return;
        ws.send(JSON.stringify({ type: "start", mime_type: mime, agent_id: agentId }));
        // send collected chunks as one? We'll send each chunk blob as binary
        chunksRef.current.forEach((b) => b.arrayBuffer().then((ab) => ws.send(ab)));
        // Actually need to send chunks; re-collect not available. Use stored arrays instead.
        ws.send(JSON.stringify({ type: "stop" }));
        stream.getTracks().forEach((t) => t.stop());
      };
      rec.start(250);
      setStatus("recording");
    }).catch((e) => setError(String(e)));
  }

  function stop() {
    recRef.current?.stop();
  }

  function end() {
    wsRef.current?.send(JSON.stringify({ type: "end" }));
    wsRef.current?.close();
  }

  useEffect(() => () => { if (ttsUrlRef.current) { URL.revokeObjectURL(ttsUrlRef.current); ttsUrlRef.current = null; } wsRef.current?.close(); }, []);

  return (
    <div style={{ padding: 8, border: "1px solid #ccc", margin: 8 }}>
      <div>Status: {status}</div>
      {error && <div style={{ color: "red" }}>{error}</div>}
      <input value={agentId} onChange={(e)=>setAgentId(e.target.value)} placeholder="agent id" />
      <button onClick={connect} disabled={status !== "idle"}>Connect</button>
      <button onClick={start} disabled={status !== "ready"}>Record</button>
      <button onClick={stop} disabled={status !== "recording"}>Stop</button>
      <button onClick={end}>End</button>
      <audio ref={audioRef} />
    </div>
  );
}
