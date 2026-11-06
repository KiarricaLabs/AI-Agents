import { useCallback, useEffect, useState } from "react";
import { listTeamGoals, humanizeAgent, type TeamGoalSummary } from "./coordination";

type WorkflowOverviewProps = {
  stage: "plans" | "review" | "execute" | "learn";
  onOpenCoordination?: () => void;
};

const STAGE_COPY = {
  plans: {
    title: "Current team plans",
    description: "These are the plans created from team delegation. Open coordination to review the full plan.",
    empty: "No delegated team plans yet. Start by delegating a request from Home.",
  },
  review: {
    title: "Delegated work awaiting review",
    description: "This is the same work shown in Home’s workflow panel, surfaced here for review.",
    empty: "No delegated work is waiting for review.",
  },
  execute: {
    title: "Team execution",
    description: "Approved team work appears here as it moves from authorization to execution and final review.",
    empty: "No team execution has started yet.",
  },
  learn: {
    title: "What the team is learning from",
    description: "The team’s active work and approved deliverables provide context for future improvements.",
    empty: "No completed team work is available to learn from yet.",
  },
} as const;

function visibleForStage(goal: TeamGoalSummary, stage: WorkflowOverviewProps["stage"]): boolean {
  if (stage === "plans") return true;
  if (stage === "review") return ["proposed", "approved", "ready_for_review", "revision_requested"].includes(goal.status);
  if (stage === "execute") return ["approved", "in_progress", "ready_for_review", "revision_requested", "completed"].includes(goal.status);
  return goal.status === "completed";
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    proposed: "Needs approval",
    approved: "Plan ready",
    in_progress: "In progress",
    ready_for_review: "Ready to review",
    revision_requested: "Changes requested",
    completed: "Complete",
    rejected: "Rejected",
  };
  return labels[status] || status.replaceAll("_", " ");
}

export function WorkflowOverview({ stage, onOpenCoordination }: WorkflowOverviewProps) {
  const [goals, setGoals] = useState<TeamGoalSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const copy = STAGE_COPY[stage];

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listTeamGoals();
      setGoals(result.items || []);
    } catch {
      setGoals([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const onChanged = () => load();
    window.addEventListener("ai-team:goal-created", onChanged);
    window.addEventListener("ai-team:workflow-updated", onChanged);
    return () => {
      window.removeEventListener("ai-team:goal-created", onChanged);
      window.removeEventListener("ai-team:workflow-updated", onChanged);
    };
  }, [load]);

  const visibleGoals = goals.filter((goal) => visibleForStage(goal, stage));

  return (
    <section className="workflow-overview" data-testid={`workflow-overview-${stage}`}>
      <div className="workflow-overview__head">
        <div>
          <h3 className="section-title">{copy.title}</h3>
          <p className="panel__sub">{copy.description}</p>
        </div>
        {onOpenCoordination && (
          <button className="btn btn--sm btn--ghost" onClick={onOpenCoordination}>
            Open full workflow
          </button>
        )}
      </div>
      {loading ? (
        <p className="muted">Loading team workflow…</p>
      ) : visibleGoals.length === 0 ? (
        <p className="muted">{copy.empty}</p>
      ) : (
        <ul className="workflow-overview__list">
          {visibleGoals.map((goal) => (
            <li key={goal.id} className="workflow-overview__item">
              <div>
                <strong>{goal.title}</strong>
                <span>Coordinator: {humanizeAgent(goal.coordinator_agent)}</span>
                {goal.expected_deliverable && <span>Result: {goal.expected_deliverable}</span>}
              </div>
              <span className={`status-chip status-chip--${goal.status}`}>{statusLabel(goal.status)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
