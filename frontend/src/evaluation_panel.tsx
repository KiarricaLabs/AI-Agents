import { useEffect, useState } from "react";

const API = (import.meta.env.VITE_API_BASE as string | undefined) || "http://127.0.0.1:8001";

const SCENARIOS = [
  ["instagram_campaign", "Instagram campaign"],
  ["email_draft", "Email draft"],
  ["business_research", "Business research"],
  ["final_exam_prep", "Final-exam preparation"],
  ["marketing_strategy", "Marketing strategy"],
  ["puerto_rico_trip", "Puerto Rico trip"],
] as const;

const FLOW_STEPS = [
  ["1", "Describe", "Tell the team what you want done."],
  ["2", "Review", "You approve the proposed plan."],
  ["3", "Execute", "Agents work locally, one step at a time."],
  ["4", "Evaluate", "Check the result before you use it."],
] as const;

function statusLabel(status: string) {
  return status.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function EvaluationPanel() {
  const [scenario, setScenario] = useState("instagram_campaign");
  const [status, setStatus] = useState("awaiting_approval");
  const [executions, setExecutions] = useState<any[]>([]);
  const [executionId, setExecutionId] = useState("");
  const [mode, setMode] = useState<"synthetic" | "execution">("synthetic");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/evaluations/executions`)
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not load executions.");
        setExecutions(data.executions || []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load executions."));
  }, []);

  async function run() {
    setLoading(true);
    setError("");
    try {
      const url = mode === "execution"
        ? `${API}/evaluations/execution/${encodeURIComponent(executionId)}?scenario=${encodeURIComponent(scenario)}`
        : `${API}/evaluations/run`;
      const response = await fetch(url, mode === "execution" ? undefined : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario,
          plan_status: status,
          agents: scenario === "email_draft" ? ["communications"]
            : scenario === "puerto_rico_trip" ? ["executive_assistant"]
            : scenario === "final_exam_prep" ? ["tutor"]
            : ["strategist", "communications"],
          output: {
            text: scenario.replace(/_/g, " "),
            published: false,
            sent: false,
            booked: false,
            charged: false,
          },
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Evaluation failed.");
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Evaluation failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="evaluation-panel" data-testid="evaluation-panel">
      <div className="evaluation-panel__hero">
        <div>
          <div className="eyebrow">YOUR CONTROL CENTER</div>
          <h3 className="evaluation-panel__title">Plan first. Act with confidence.</h3>
          <p className="evaluation-panel__intro">
            Every request follows the same safe path: your team proposes a plan,
            you approve it, then local agents execute and show their work.
          </p>
        </div>
        <div className="evaluation-panel__safe">
          <span className="evaluation-panel__safe-dot" aria-hidden="true" />
          <div><strong>Local-only mode</strong><span>Nothing is sent or booked</span></div>
        </div>
      </div>

      <div className="evaluation-flow" aria-label="Workflow steps">
        {FLOW_STEPS.map(([number, title, description]) => (
          <div className="evaluation-flow__step" key={number}>
            <span className="evaluation-flow__number">{number}</span>
            <div><strong>{title}</strong><span>{description}</span></div>
          </div>
        ))}
      </div>

      <div className="evaluation-panel__body">
        <div className="evaluation-panel__section-head">
          <div>
            <h4>Check a workflow</h4>
            <p>Use a practice check while training, or inspect a real execution.</p>
          </div>
          <span className="evaluation-panel__status">{mode === "synthetic" ? "Practice mode" : "Read-only report"}</span>
        </div>

        <div className="evaluation-form">
          <label>
            <span>What are you testing?</span>
            <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {SCENARIOS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            <span>Where should we look?</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as "synthetic" | "execution")}>
              <option value="synthetic">Practice scenario</option>
              <option value="execution">A real execution</option>
            </select>
          </label>
          {mode === "synthetic" && <label>
            <span>Workflow stage</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="awaiting_approval">Before approval</option>
              <option value="approved">Approved and ready</option>
              <option value="completed">Completed</option>
            </select>
          </label>}
          {mode === "execution" && <label>
            <span>Choose an execution</span>
            <select value={executionId} onChange={(e) => setExecutionId(e.target.value)}>
              <option value="">Select an execution</option>
              {executions.map((item) => (
                <option key={item.execution_id} value={item.execution_id}>
                  {item.execution_id.slice(0, 8)} · {statusLabel(item.status)}
                </option>
              ))}
            </select>
          </label>}
          <button className="btn btn--primary evaluation-form__button" onClick={run}
            disabled={loading || (mode === "execution" && !executionId)}>
            {loading ? "Checking…" : mode === "synthetic" ? "Run practice check" : "Evaluate execution"}
          </button>
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <div className={`evaluation-results ${result.passed ? "evaluation-results--passed" : "evaluation-results--attention"}`} data-testid="evaluation-results">
          <div className="evaluation-results__head">
            <div>
              <span className="evaluation-results__kicker">Evaluation report</span>
              <strong>{result.passed ? "Ready for your review" : "Needs attention"}</strong>
            </div>
            <span className={`evaluation-results__icon ${result.passed ? "is-passed" : "is-attention"}`} aria-hidden="true">
              {result.passed ? "✓" : "!"}
            </span>
          </div>
          <ul className="list">
            {result.checks.map((check: any) => (
              <li key={check.name}>
                <span className={`badge badge--${check.passed ? "completed" : "blocked"}`}>
                  {check.passed ? "pass" : "fail"}
                </span>{" "}
                {check.name}: {check.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
