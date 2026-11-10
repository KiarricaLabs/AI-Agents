import { useEffect, useRef } from "react";
export function VoiceIndicator({ active, analyser }: { active: boolean; analyser?: AnalyserNode | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!active || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    let raf: number;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      ctx.clearRect(0,0,canvas.width,canvas.height);
      if (analyser) {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        for(let i=0;i<12;i++){
          const v=data[i*2]||0;
          const h=(v/255)*28+4;
          ctx.fillStyle="#6b7cff";
          ctx.fillRect(i*12+2, 16-h/2, 8, h);
        }
      } else {
        const t=Date.now()/200;
        for(let i=0;i<5;i++){ const h=10+Math.sin(t+i)*8+Math.random()*4; ctx.fillStyle="#6b7cff"; ctx.fillRect(i*14+4, 16-h/2, 8, h); }
      }
    };
    draw();
    return ()=>cancelAnimationFrame(raf);
  }, [active, analyser]);
  if (!active) return null;
  return <canvas ref={canvasRef} width={140} height={32} style={{ borderRadius: 8, background: "#1c1f25" }} />;
}
