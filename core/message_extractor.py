"""Phase 4 §8 — Conversation → TeamGoal extraction (deterministic).

Turns a human message (a discussion / idea / brief) into an editable TeamGoal
DRAFT (title, summary, expected_deliverable, coordinator, ordered steps with
dependency chaining). This is a DRAFT GENERATOR: it never persists anything, it
only produces a structured proposal the human can edit and then propose through
the existing human-only `POST /team/goals` flow.

Extraction is deterministic and rule-based (no live model), so it is fully
testable and safe:
- Title   : a leading "title:/goal:/topic:" line, else the first line (capped).
- Summary : the remaining text (joined).
- Deliverable : an explicit "deliverable:/outcome:/produce:/want:" line if present.
- Steps   : explicit bullet/numbered lines of the form "<word>: <task>" /
            "<word> - <task>". A recognized agent slug is kept as its owner; an
            unknown prefix falls back to the coordinator. Free-text prose (no
            colon/dash) is treated as summary, NOT as steps. If no structured
            step line is found, a single default step using the coordinator is
            produced. Steps get contiguous 1..n sequences and each later step
            depends on the previous one (ordering preserved).

No approval, plan authorization, or execution is ever triggered here.
"""
from __future__ import annotations

import re
from typing import Dict, List

from core.team_goal import AGENT_SLUGS


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


class MessageToTeamGoal:
    @staticmethod
    def extract(message: str, coordinator_agent: str) -> Dict[str, object]:
        coordinator = str(coordinator_agent or "").strip().lower()
        if coordinator not in AGENT_SLUGS:
            raise ValueError(f"unknown coordinator agent: {coordinator}")
        text = _clean(message)
        if not text:
            raise ValueError("message is required")

        raw_lines = [l.strip() for l in str(message).splitlines() if l.strip()]
        if not raw_lines:
            raw_lines = [text]

        title, body_lines = _split_title(raw_lines)
        summary = _clean(" ".join(body_lines)) or None
        deliverable = _extract_deliverable("\n".join(raw_lines))
        steps = _extract_steps(body_lines, coordinator)

        return {
            "title": title,
            "summary": summary,
            "expected_deliverable": deliverable,
            "coordinator_agent": coordinator,
            "steps": steps,
        }


def _is_step_line(line: str) -> bool:
    return bool(re.match(r"^[\-\*#\d\.\)\s]*\w+\s*[:\-]\s*.+$", line.strip(), re.I))


def _split_title(lines: List[str]):
    if not lines:
        return "Untitled", []
    m = re.match(r"^(?:title|goal|topic)\s*[:\-]\s*(.+)$", lines[0], re.I)
    if m:
        return _cap(m.group(1)), list(lines[1:])
    # pick the first non-step line as the prose title (skip step lines)
    for i, ln in enumerate(lines):
        if not _is_step_line(ln):
            return _cap(ln), [x for j, x in enumerate(lines) if j != i]
    # every line is a step line -> no prose title available
    return "New Team Goal", list(lines)


def _cap(s: str) -> str:
    s = _clean(s)
    return s[:120] or "Untitled"


def _extract_deliverable(text: str):
    for m in re.finditer(
        r"(?:deliverable|outcome|produce|want)\s*[:\-]\s*(.{3,200})",
        text, re.I):
        val = m.group(1).strip().rstrip(".")
        if val:
            return val[:200]
    return None


def _extract_steps(body_lines: List[str], coordinator: str) -> List[Dict[str, object]]:
    """Only explicit '<word>: task' / '<word> - task' lines become steps.
    A recognized slug is kept as its owner; an unknown prefix falls back to the
    coordinator. Free-text prose (no colon/dash) is ignored here (kept as summary)."""
    pattern = re.compile(r"^[\-\*#\d\.\)\s]*(\w+)\s*[:\-]\s*(.+)$", re.I)
    steps: List[Dict[str, object]] = []
    for line in body_lines:
        # a deliverable/outcome/produce marker line is the deliverable, not a step
        if re.match(r"^(?:deliverable|outcome|produce|want)\s*[:\-]", line, re.I):
            continue
        m = pattern.match(line)
        if not m:
            continue
        agent_raw = m.group(1).lower()
        task = _clean(m.group(2))
        if len(task) < 3:
            continue
        agent = agent_raw if agent_raw in AGENT_SLUGS else coordinator
        steps.append({"agent_id": agent, "responsibility": task})

    if not steps:
        steps.append({"agent_id": coordinator, "responsibility": "Coordinate and deliver the goal"})

    norm = []
    for i, s in enumerate(steps):
        agent = s["agent_id"] if s["agent_id"] in AGENT_SLUGS else coordinator
        norm.append({
            "seq": i + 1,
            "agent_id": agent,
            "responsibility": s["responsibility"],
            "depends_on_seq": None if i == 0 else i,
        })
    return norm
