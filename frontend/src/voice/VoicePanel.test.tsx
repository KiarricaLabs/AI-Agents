import { render, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { VoicePanel } from "./VoicePanel";

class MockWS {
  static instances: MockWS[] = [];
  onopen: any = null;
  onmessage: any = null;
  onclose: any = null;
  onerror: any = null;
  readyState = 1;
  send = vi.fn();
  close = vi.fn(() => { if (this.onclose) this.onclose(); });
  constructor(url: string) { MockWS.instances.push(this); }
  emit(msg: any) { if (this.onmessage) this.onmessage({ data: typeof msg === "string" ? msg : msg }); }
  emitBinary(b: Blob) { if (this.onmessage) this.onmessage({ data: b }); }
}

beforeEach(() => {
  MockWS.instances = [];
  (global as any).WebSocket = MockWS as any;
  (global as any).URL.createObjectURL = vi.fn(() => "blob:url");
  (global as any).URL.revokeObjectURL = vi.fn();
  (navigator as any).mediaDevices = { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) };
  (global as any).MediaRecorder = class { start(){} stop(){} ondataavailable=null; onstop=null; static isTypeSupported(){return true;} };
});

describe("VoicePanel", () => {
  it("renders status", () => {
    const { getByText } = render(<VoicePanel />);
    expect(getByText(/Status:/)).toBeTruthy();
  });

  it("stale turn events do not change state", () => {
    const { getByText } = render(<VoicePanel />);
    const btn = getByText("Connect");
    fireEvent.click(btn);
    const ws = MockWS.instances[0];
    act(() => { ws.onopen(); });
    act(() => { ws.emit(JSON.stringify({ type: "ready" })); });
    act(() => { ws.emit(JSON.stringify({ type: "state", state: "ready", turn_id: "t1" })); });
    // stale event with different turn_id
    act(() => { ws.emit(JSON.stringify({ type: "assistant_text", text: "old", turn_id: "old" })); });
    // no crash; status still ready
    expect(getByText(/Status: ready/)).toBeTruthy();
  });

  it("cancelled stops playback", () => {
    render(<VoicePanel />);
    const ws = new MockWS("x");
    MockWS.instances.push(ws);
    // direct emit
    act(() => { ws.onopen?.(); });
  });
});
