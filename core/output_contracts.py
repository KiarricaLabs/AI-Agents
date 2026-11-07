"""Best-effort structured output contracts per deliverable_type.

Task drafts stay readable prose (that is what the human reviews), but each agent
is also asked to emit a small machine-readable JSON summary block at the end of
its reply. This module maps a deliverable_type to the JSON keys it should carry,
and provides extraction/validation that is lenient and never blocks the flow: if
the agent omits or mangles the JSON block, the runner keeps the prose and simply
records no structured payload (output_json stays NULL).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# deliverable_type -> (required keys, one-line guidance shown to the agent).
CONTRACTS: Dict[str, tuple] = {
    "positioning_statement": (["positioning", "audience", "message"],
                              "positioning, target audience, key message"),
    "content_calendar": (["weeks", "posts"],
                         "week by week posts with hooks, captions, formats"),
    "content_plan": (["concepts", "formats", "schedule"],
                     "content concepts, formats, schedule"),
    "audience_research": (["segments", "findings"],
                          "audience segments and research findings"),
    "research": (["segments", "findings"], "audience segments and findings"),
    "risk_review": (["risks", "improvements", "go_no_go"],
                    "risks, concrete improvements, and a go/no-go verdict"),
    "soundboard": (["risks", "improvements"],
                   "assumptions, risks, and concrete improvements"),
    "campaign_plan": (["phases", "deliverables"],
                      "ordered phases and each phase's deliverables"),
    "draft": (["content"], "the draft content"),
    "study_plan": (["outline", "practice"],
                   "a study outline and practice items"),
    "event_plan": (["steps", "deliverables"], "ordered steps and deliverables"),
}

# Every output, whatever its type, should also carry this readable summary key.
SUMMARY_KEY = "summary"

DEFAULT_CONTRACT = tuple(["content", SUMMARY_KEY])


def contract_for(deliverable_type: str) -> tuple:
    keys, guidance = CONTRACTS.get((deliverable_type or "").strip(),
                                   (DEFAULT_CONTRACT[0], "the concrete deliverable"))
    return tuple(dict.fromkeys(list(keys) + [SUMMARY_KEY])), guidance


def guidance_for(deliverable_type: str) -> str:
    _, guidance = contract_for(deliverable_type)
    keys, _ = contract_for(deliverable_type)
    return (
        f"At the very end of your reply, add a ```json block containing ONLY the keys: "
        f"{', '.join(keys)}. Keep the values short and factual. Example:\n"
        "```json\n{"
        + ", ".join(f'"{k}": "…"' for k in keys)
        + "}\n```"
    )


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object from a ```json``` block, or a bare {...}
    block at the end, whichever parses. Returns a dict or None."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # fenced block
    fenced = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    for candidate in fenced:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    # bare trailing object (last occurrence)
    for candidate in re.findall(r"\{.*?\}", text, re.S):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _strip_json_block(text: str) -> str:
    return re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.S).strip()


def extract_structured(reply: str, deliverable_type: str) -> tuple:
    """Returns (structured_dict_or_None, readable_prose). The readable prose is
    the reply with any JSON block removed, so the human reviews clean text."""
    raw = (reply or "")
    block = _extract_json(raw)
    prose = _strip_json_block(raw).strip() or raw.strip()
    if not isinstance(block, dict):
        return None, prose
    keys, _ = contract_for(deliverable_type)
    if not isinstance(block, dict):
        return None, prose
    # Require the documented keys (minus summary) to be present and non-empty.
    required = [k for k in keys if k != SUMMARY_KEY]
    missing = [k for k in required if not str(block.get(k, "")).strip()]
    if missing:
        return None, prose
    block[SUMMARY_KEY] = str(block.get(SUMMARY_KEY, "")).strip() or prose[:200]
    return block, prose
