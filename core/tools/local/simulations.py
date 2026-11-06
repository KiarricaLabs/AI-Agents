"""Credential-free local simulation tools.

These tools create honest, structured previews for future external actions.
They never use the network, credentials, or real external accounts.
"""
from __future__ import annotations

from typing import Any, Optional

from core.tools import Tool


def _text(args: dict, key: str, required: bool = True) -> str:
    value = str(args.get(key) or "").strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    return value


class SimulateEmailTool(Tool):
    name = "simulate_email"
    description = "Prepare a local email draft; never sends email."

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        return {
            "action": "email",
            "status": "simulated",
            "performed": False,
            "sent": False,
            "recipient": _text(args, "recipient"),
            "subject": _text(args, "subject"),
            "body": _text(args, "body"),
            "message": "Draft prepared locally. No email was sent.",
        }


class SimulateSocialCampaignTool(Tool):
    name = "simulate_social_campaign"
    description = "Prepare a local social campaign; never publishes content."

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        return {
            "action": "social_campaign",
            "status": "simulated",
            "performed": False,
            "published": False,
            "platform": _text(args, "platform"),
            "campaign": _text(args, "campaign"),
            "content": args.get("content") or [],
            "message": "Campaign prepared locally. Nothing was published.",
        }


class SimulateResearchTool(Tool):
    name = "simulate_research"
    description = "Return clearly labeled local research fixtures; never browses."

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        topic = _text(args, "topic")
        findings = args.get("findings") or []
        return {
            "action": "research",
            "status": "simulated",
            "performed": False,
            "source_type": "local_fixture",
            "topic": topic,
            "findings": findings,
            "message": "Research used local fixture data. No web research was performed.",
        }


class SimulateTravelTool(Tool):
    name = "simulate_travel"
    description = "Prepare a local travel itinerary; never books or charges."

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        destination = _text(args, "destination")
        return {
            "action": "travel",
            "status": "simulated",
            "performed": False,
            "booked": False,
            "charged": False,
            "destination": destination,
            "options": args.get("options") or [],
            "message": "Itinerary prepared locally. Nothing was booked or charged.",
        }


class SaveLocalArtifactTool(Tool):
    name = "save_local_artifact"
    description = "Return a local artifact payload for the caller to persist."

    def run(self, args: dict, context: Optional[dict] = None) -> Any:
        return {
            "action": "save_local_artifact",
            "status": "ready",
            "performed": False,
            "artifact_type": _text(args, "artifact_type"),
            "content": args.get("content"),
            "message": "Artifact is ready for local persistence; no external service was used.",
        }
