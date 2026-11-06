import { useEffect, useState } from "react";

const NOTES_KEY = "pat.commandCenter.notes";

export function CommandCenterSidebar() {
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setNotes(localStorage.getItem(NOTES_KEY) || "");
  }, []);

  function saveNotes(value: string) {
    setNotes(value);
    localStorage.setItem(NOTES_KEY, value);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1200);
  }

  return (
    <aside className="command-rail" aria-label="Command center tools">
      <section className="command-card command-card--notes">
        <div className="command-card__head">
          <div>
            <span className="command-card__eyebrow">PRIVATE SPACE</span>
            <h3>Notes to self</h3>
          </div>
          <span className="command-card__sparkle" aria-hidden="true">✦</span>
        </div>
        <textarea
          value={notes}
          onChange={(event) => saveNotes(event.target.value)}
          placeholder="Capture an idea, preference, or reminder…"
          aria-label="Private notes"
        />
        <span className="command-card__hint">{saved ? "Saved on this device" : "Private local notes"}</span>
      </section>

      <section className="command-card">
        <div className="command-card__head">
          <div>
            <span className="command-card__eyebrow">READY WHEN YOU ARE</span>
            <h3>Connections</h3>
          </div>
          <span className="command-card__lock" aria-hidden="true">⌁</span>
        </div>
        <p className="command-card__copy">
          Add accounts only when you decide the team is ready for real-world actions.
        </p>
        <div className="connection-row">
          <span className="connection-row__icon">◎</span>
          <div><strong>Email</strong><span>Not connected</span></div>
          <button className="btn btn--sm btn--ghost" disabled>Later</button>
        </div>
        <div className="connection-row">
          <span className="connection-row__icon">◌</span>
          <div><strong>Social accounts</strong><span>Not connected</span></div>
          <button className="btn btn--sm btn--ghost" disabled>Later</button>
        </div>
        <p className="command-card__safe">Credentials stay locked until you explicitly add them.</p>
      </section>

      <section className="command-card command-card--guide">
        <span className="command-card__eyebrow">HOW IT WORKS</span>
        <h3>You stay in charge</h3>
        <p>Agents can suggest, delegate, and prepare. Nothing executes until you approve it.</p>
        <div className="approval-pill"><span>✓</span> Approval required at every step</div>
      </section>
    </aside>
  );
}
