"""Integration registry (Phase D)."""
from typing import Dict, Optional
from integrations import Integration

_REGISTRY: Dict[str, Integration] = {}


def register(integration: Integration):
    _REGISTRY[integration.name] = integration


def get(name: str) -> Optional[Integration]:
    return _REGISTRY.get(name)


def list_integrations() -> list:
    return list(_REGISTRY.keys())
"""