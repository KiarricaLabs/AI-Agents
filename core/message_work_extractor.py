"""Phase 5 §9 & Phase 6 §11 — Conversation → Assignment / Deliverable extraction.

Deterministic, rule-based draft generators (no live model) that turn a human
message — "assign research on the market to strategist" / "produce a one-page
launch plan" — into an EDITABLE assignment or deliverable draft.

These are DRAFT GENERATORS and DRAFT VALIDATORS: they persist nothing. The draft
must then be proposed through the existing human-only ``POST /work/proposals``
flow (the backend's WorkProposalService) and approved by a human before any real
record is created. No approval, plan authorization, or execution is ever
triggered here.

Parsing conventions (mirroring core/message_extractor):
- Title / task   : a leading "task:/assign:/do:" (assignment) or
  "deliverable:/create:/produce:" (deliverable) line, else the first line.
- Subject agent  : an explicit "to:<agent>" / "assign ... to <agent>" is honored;
  otherwise the provided ``subject_agent`` is used. Unknown slugs are rejected.
- Expected output: an "output:/deliver:/produce:" (assignment) line.
- Priority       : a "priority:<text>" line, else None.
- Format         : a "format:<text>" line, else None.
- Description    : the remaining prose (joined).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from core.team_goal import AGENT_SLUGS


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _cap(s: str, limit: int = 120) -> str:
    s = _clean(s)
    return s[:limit] or "Untitled"


def _lines(message: str) -> List[str]:
    return [ln.strip() for ln in str(message or "").splitlines()]


def _match_first(patterns, lines, default=None):
    for ln in lines:
        for pat in patterns:
            m = re.match(pat, ln, re.I)
            if m and m.lastindex:
                return _clean(m.group(1)).rstrip(".")
    return default


def _subject_from_text(message: str, fallback: str) -> str:
    candidate = (fallback or "").strip().lower()
    # explicit "to X" / "to: X" / "assign ... to X".
    for pat in (r"\bto\s*:?\s*([a-z_]+)\b",
                r"\bassign\b.+?\bto\s*:?\s*([a-z_]+)\b"):
        m = re.search(pat, message, re.I)
        if m and m.group(1).lower() in AGENT_SLUGS:
            candidate = m.group(1).lower()
            break
    else:
        # a line starting with a recognized agent slug "slug: ..." / "slug - ...".
        for ln in _lines(message):
            m = re.match(r"^([a-z_]+)\s*[:\-]\s*.+$", ln, re.I)
            if m and m.group(1).lower() in AGENT_SLUGS:
                candidate = m.group(1).lower()
                break
    candidate = candidate.strip().lower()
    if not candidate or candidate not in AGENT_SLUGS:
        raise ValueError(f"unknown agent: {candidate}")
    return candidate


class MessageToAssignment:
    """Parse a request to assign a task to an agent into an editable draft."""

    @staticmethod
    def extract(message: str, subject_agent: Optional[str] = None) -> Dict[str, object]:
        text = _clean(message)
        if not text:
            raise ValueError("message is required")
        lines = _lines(message)

        subject = _subject_from_text(message, subject_agent or "")

        title = _match_first(
            [(r"^(?:task|assign|do|todo)\s*[:\-]\s*(.+)$")],
            lines,
        ) or _cap(lines[0] if lines else "New assignment")

        expected_output = _match_first(
            [(r"^(?:output|deliver|produce)\s*[:\-]\s*(.+)$")],
            lines,
        )
        priority = _match_first(
            [(r"^priority\s*[:\-]\s*(.+)$")],
            lines,
        )

        return {
            "kind": "assignment",
            "title": title,
            "subject_agent": subject,
            "expected_output": expected_output,
            "priority": priority,
            "source_context": "conversation",
        }


class MessageToDeliverable:
    """Parse a request to produce a deliverable into an editable draft."""

    @staticmethod
    def extract(message: str, owner_agent: Optional[str] = None) -> Dict[str, object]:
        text = _clean(message)
        if not text:
            raise ValueError("message is required")
        lines = _lines(message)

        owner = (owner_agent or "").strip().lower()
        # explicit "by X" / "by: X" — reject an unknown explicit agent.
        by = re.search(r"\bby\s*:?\s*([a-z_]+)\b", text, re.I)
        if by:
            b = by.group(1).lower()
            if b not in AGENT_SLUGS:
                raise ValueError(f"unknown agent: {b}")
            responsible_agent = b
        else:
            candidate = owner
            if not candidate:
                # a line starting with a recognized agent slug.
                for ln in lines:
                    m = re.match(r"^([a-z_]+)\s*[:\-]\s*.+$", ln, re.I)
                    if m and m.group(1).lower() in AGENT_SLUGS:
                        candidate = m.group(1).lower()
                        break
            if candidate and candidate not in AGENT_SLUGS:
                raise ValueError(f"unknown agent: {candidate}")
            responsible_agent = candidate or None

        title = _match_first(
            [(r"^(?:deliverable|create|produce|generate)\s*[:\-]\s*(.+)$")],
            lines,
        ) or _cap(lines[0] if lines else "New deliverable")

        fmt = _match_first(
            [(r"^format\s*[:\-]\s*(.+)$")],
            lines,
        )
        description = _clean(" ".join(lines[1:])) or None

        return {
            "kind": "deliverable",
            "title": title,
            "format": fmt,
            "responsible_agent": responsible_agent,
            "description": description,
            "source_context": "conversation",
        }


class MessageToProject:
    """Phase 4 §7 — parse an idea to build a project into an editable draft."""

    @staticmethod
    def extract(message: str) -> Dict[str, object]:
        text = _clean(message)
        if not text:
            raise ValueError("message is required")
        lines = _lines(message)
        title = _match_first(
            [(r"^project\s*[:\-]\s*(.+)$"), (r"^(?:build|create|make)\s*(?:a|an)?\s*(.+)$")],
            lines,
        ) or _cap(lines[0] if lines else "New project")
        description = _clean(" ".join(lines[1:])) or None
        return {"kind": "project", "title": title, "description": description,
                "source_context": "conversation"}


class MessageToGoal:
    """Phase 4 §8 — parse an objective into an editable goal draft."""

    @staticmethod
    def extract(message: str) -> Dict[str, object]:
        text = _clean(message)
        if not text:
            raise ValueError("message is required")
        lines = _lines(message)
        title = _match_first(
            [(r"^goal\s*[:\-]\s*(.+)$"), (r"^(?:objective|outcome)\s*[:\-]\s*(.+)$")],
            lines,
        ) or _cap(lines[0] if lines else "New goal")
        description = _clean(" ".join(lines[1:])) or None
        return {"kind": "goal", "title": title, "description": description,
                "source_context": "conversation"}


class MessageToPlan:
    """Parses a planning brief into an editable plan draft (title + milestones +
    deliverables). Deterministic and rule-based like the other extractors, so it
    is testable and never persists anything."""

    @staticmethod
    def extract(message: str) -> Dict[str, object]:
        text = _clean(message)
        if not text:
            raise ValueError("message is required")
        lines = _lines(message)
        title = _match_first([(r"^plan\s*[:\-]\s*(.+)$")], lines) \
            or _cap(lines[0] if lines else "New plan")
        milestones: List[Dict[str, object]] = []
        deliverables: List[Dict[str, str]] = []
        for i, ln in enumerate(lines):
            m = re.match(r"^(?:milestone|phase)\s*[:\.\-]?\s*([^,;]+)$", ln, re.I)
            if m and m.group(1).strip():
                milestones.append({"title": _cap(m.group(1), 200), "order": i})
                continue
            d = re.match(r"^(?:deliverable|produce|output)\s*[:\.\-]?\s*(.+)$", ln, re.I)
            if d and d.group(1).strip():
                deliverables.append({"title": _cap(d.group(1), 200)})
        if not milestones:
            milestones.append({"title": f"Phase 1 — {_cap(title, 40)}", "order": 0})
        if not deliverables:
            deliverables.append({"title": _cap(title, 60) + " deliverable"})
        return {"kind": "plan", "title": title,
                "milestones": milestones, "deliverables": deliverables,
                "source_context": "conversation"}


# Dispatch so the API can call either extractor by kind.
EXTRACTORS = {
    "assignment": MessageToAssignment.extract,
    "deliverable": MessageToDeliverable.extract,
    "project": MessageToProject.extract,
    "goal": MessageToGoal.extract,
    "plan": MessageToPlan.extract,
}
