// Phase 7 §13 — Review & Action Center.
//
// A read-only aggregate of everything that needs the human owner's attention
// across all of their TeamGoals/plans/executions/steps/deliverables, with inline
// actions where appropriate. It NEVER approves/authorizes/executes on its own —
// approving a goal calls the human-only POST /team/goals/{id}/approve, and every
// other item opens the coordination view for an explicit human decision.
import { useCallback, useEffect, useState } from "react";
import {
  getReviewCenter,
  approveTeamGoal,
  dismissReviewItem,
  humanizeAgent,
  type ReviewCenterResult,
  type ReviewItem,
} from "./coordination";

function rcErr(e: unknown, fallback: string): string {
  return (e && typeof e === "object" && "message" in e && typeof (e as any).message === "string"
    ? (e as any).message : fallback);
}

const TYPE_LABEL: Record<string, string> = {
  goal_approval: "Team goal approvals",
  plan_authorization: "Plans awaiting authorization",
  step_review: "Steps awaiting review",
  deliverable_review: "Deliverables awaiting review",
  blocked_step: "Blocked / failed steps",
  blocked_communication: "Blocked agent coordination",
};

// Order sections sensibly in the hub.
const SECTION_ORDER = ["goal_approval", "plan_authorization", "step_review",
  "deliverable_review", "blocked_step", "blocked_communication"];

export function ReviewCenter({ onOpen }: { onOpen?: (goalId?: string) => void }) {
  const [data, setData] = useState<ReviewCenterResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getReviewCenter());
    } catch (e) {
      setError(rcErr(e, "Could not load the review center."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function doApprove(item: ReviewItem) {
    if (!item.goal_id) return;
    setBusy(item.goal_id);
    setError("");
    try {
      await approveTeamGoal(item.goal_id);
      await load();
    } catch (e) {
      setError(rcErr(e, "Could not approve the team goal."));
    } finally {
      setBusy(null);
    }
  }

  async function doDismiss(item: ReviewItem) {
    if (!item.type || !item.key) return;
    setBusy(item.key);
    setError("");
    try {
      await dismissReviewItem(item.type, item.key);
      await load();
    } catch (e) {
      setError(rcErr(e, "Could not dismiss the item."));
    } finally {
      setBusy(null);
    }
  }

  const counts = data?.counts || {};
  const total = Object.keys(counts).reduce((s, k) => s + (counts[k] || 0), 0);

  return (
    <section className="panel review-center-panel" data-testid="review-center">
      <div className="panel__head">
        <div>
          <h3 className="section-title">Review &amp; Action Center</h3>
          <p className="panel__sub">Everything that needs your attention, in one place.</p>
        </div>
        <button className="btn btn--sm btn--ghost" data-testid="review-refresh" onClick={load}>
          {total > 0 ? `${total} pending` : "Refresh"}
        </button>
      </div>

      {loading && <div className="empty">Loading your pending decisions…</div>}
      {error && <p className="error" role="alert">{error}</p>}

      {!loading && !error && total === 0 && (
        <div className="empty" data-testid="review-empty">
          Nothing needs your attention right now.
        </div>
      )}

      {!loading && data && total > 0 && (
        <div data-testid="review-sections">
          {SECTION_ORDER.filter((t) => (counts[t] || 0) > 0).map((type) => {
            const items = data.items.filter((i) => i.type === type);
            return (
              <div className="coord-block" key={type} data-testid={`review-section-${type}`}>
                <h5 className="section-title">{TYPE_LABEL[type]} ({items.length})</h5>
                <ul className="list">
                  {items.map((it, idx) => (
                    <li key={`${type}-${idx}`} className="list__item" data-testid={`review-item-${type}`}>
                      <ReviewItemRow item={it} busy={busy} onApprove={doApprove} onDismiss={doDismiss} onOpen={onOpen} />
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function ReviewItemRow({ item, busy, onApprove, onDismiss, onOpen }: {
  item: ReviewItem;
  busy: string | null;
  onApprove: (i: ReviewItem) => void;
  onDismiss?: (i: ReviewItem) => void;
  onOpen?: (goalId?: string) => void;
}) {
  const open = onOpen ? () => onOpen(item.goal_id) : undefined;
  const title = item.title || item.goal_title ||
    (item.type === "blocked_communication" ? "Coordination loop blocked" : "—");
  const subtitle =
    item.type === "step_review" || item.type === "blocked_step"
      ? `Step ${item.seq} · ${humanizeAgent(item.agent_id)}`
      : item.type === "blocked_communication"
        ? `${humanizeAgent(item.from_agent)} → ${humanizeAgent(item.to_agent)}`
        : humanizeAgent(item.coordinator_agent);

  const errorText =
    item.type === "blocked_communication"
      ? `${item.content || ""} ${item.message || ""}`.slice(0, 140)
      : item.error || "";

  return (
    <div className="review-row" data-testid={`review-row-${item.type}`}>
      <div className="review-row__main">
        <span className="review-row__title">{title}</span>
        {subtitle && <span className="muted review-row__meta">{subtitle}</span>}
        {errorText && (
          <span className="warning review-row__error">{errorText}</span>
        )}
      </div>
      <div className="coord-step__actions">
        {item.type === "goal_approval" && (
          <button className="btn btn--sm btn--primary" data-testid="review-approve"
            onClick={() => onApprove(item)} disabled={busy !== null}>
            {busy === item.goal_id ? "Approving…" : "Approve"}
          </button>
        )}
        {onDismiss && (
          <button className="btn btn--sm btn--ghost" data-testid={`review-dismiss-${item.type}`}
            title="Hide this from the review list (keeps all evidence)"
            onClick={() => onDismiss(item)} disabled={busy !== null}>
            Dismiss
          </button>
        )}
        {open && (
          <button className="btn btn--sm btn--ghost" data-testid="review-open"
            onClick={open}>Open in AI Team</button>
        )}
      </div>
    </div>
  );
}
