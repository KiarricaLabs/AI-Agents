"""Integration framework (Phase D1). Human-gated external actions."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Integration(ABC):
    name: str = "base"

    @abstractmethod
    def connect(self, credentials: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health(self) -> Dict[str, Any]: ...

    @abstractmethod
    def execute(self, action: str, params: Dict[str, Any], *,
                approved: bool = False) -> Dict[str, Any]:
        """Execute an action. Mutating actions require approved=True (human gate)."""
        ...

    def requires_approval(self, action: str) -> bool:
        return True