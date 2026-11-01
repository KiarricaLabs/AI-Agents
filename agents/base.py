from __future__ import annotations

from typing import Any, Dict, Optional
from core.memory import MemoryService


class BaseAgent:
    name: str = "base"
    manifest: Dict[str, Any] = {}

    def __init__(self, memory: MemoryService, model_router=None):
        self.memory = memory
        self.model_router = model_router

    def run(self, task: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError