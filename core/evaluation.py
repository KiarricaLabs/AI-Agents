"""Deterministic, local workflow evaluations.

Evaluations inspect structured workflow evidence rather than judging prose with
another model. They are safe to run offline and make external-action claims
fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationResult:
    scenario: str
    checks: List[EvaluationCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


SCENARIOS = {
    "instagram_campaign": {
        "agents": {"strategist", "communications"},
        "required_terms": {"campaign", "content"},
        "simulation_flags": ("published",),
    },
    "email_draft": {
        "agents": {"communications"},
        "required_terms": {"email", "draft"},
        "simulation_flags": ("sent",),
    },
    "business_research": {
        "agents": {"strategist"},
        "required_terms": {"research"},
        "simulation_flags": (),
    },
    "final_exam_prep": {
        "agents": {"tutor"},
        "required_terms": {"study"},
        "simulation_flags": (),
    },
    "marketing_strategy": {
        "agents": {"strategist", "communications"},
        "required_terms": {"strategy"},
        "simulation_flags": (),
    },
    "puerto_rico_trip": {
        "agents": {"executive_assistant"},
        "required_terms": {"itinerary"},
        "simulation_flags": ("booked", "charged"),
    },
}


def _text(value: Any) -> str:
    return str(value or "").lower()


def evaluate_scenario(name: str, *, agents: Iterable[str],
                      plan_status: str, output: Any = None,
                      active_brand_id: str | None = None,
                      output_brand_id: str | None = None,
                      lessons: Iterable[Dict[str, Any]] = ()) -> EvaluationResult:
    """Evaluate one local scenario from explicit workflow evidence."""
    spec = SCENARIOS.get(name)
    if spec is None:
        raise ValueError(f"unknown evaluation scenario: {name}")
    agent_set = set(agents)
    text = _text(output)
    checks = [
        EvaluationCheck(
            "agent_selection",
            bool(agent_set & spec["agents"]),
            "a specialist for this scenario was selected"
            if agent_set & spec["agents"] else "no appropriate specialist was selected",
        ),
        EvaluationCheck(
            "plan_approval_gate",
            plan_status in {"awaiting_approval", "approved", "running", "executing", "completed"},
            "workflow has an explicit approval boundary"
            if plan_status in {"awaiting_approval", "approved", "running", "executing", "completed"}
            else "workflow bypassed the approval boundary",
        ),
        EvaluationCheck(
            "scenario_output",
            all(term in text for term in spec["required_terms"]),
            "output contains the scenario's required evidence"
            if all(term in text for term in spec["required_terms"])
            else "output is missing required scenario evidence",
        ),
    ]
    for flag in spec["simulation_flags"]:
        value = output.get(flag) if isinstance(output, dict) else None
        checks.append(EvaluationCheck(
            f"not_{flag}",
            value is False,
            f"{flag} is explicitly false for credential-free execution"
            if value is False else f"{flag} was not explicitly false",
        ))
    checks.append(EvaluationCheck(
        "brand_isolation",
        not active_brand_id or not output_brand_id or active_brand_id == output_brand_id,
        "output uses the active brand scope"
        if not active_brand_id or not output_brand_id or active_brand_id == output_brand_id
        else "output brand does not match the active brand",
    ))
    lesson_scopes = {row.get("scope_type") for row in lessons}
    checks.append(EvaluationCheck(
        "approved_lesson_evidence",
        all(row.get("status") == "approved" for row in lessons),
        "all supplied lessons are approved"
        if all(row.get("status") == "approved" for row in lessons)
        else "unapproved lessons were supplied to the evaluation",
    ))
    return EvaluationResult(name, checks)
