"""`now` tool: current wall-clock time (UTC + local).

Purely informational, deterministic given the clock, and explicitly
not consequential. No external services.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.tools import Tool


class NowTool(Tool):
    name = "now"
    description = "Return the current time as ISO 8601 UTC and local wall-clock strings."
    consequential = False

    def run(self, args: Optional[dict] = None, context: Optional[dict] = None) -> Any:
        utc = datetime.now(timezone.utc)
        local = datetime.now().astimezone()
        return {"utc": utc.isoformat(), "local": local.isoformat()}
