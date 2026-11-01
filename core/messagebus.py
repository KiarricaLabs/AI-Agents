"""Tenant-scoped in-memory MessageBus with topic authorization."""
from __future__ import annotations

from typing import Dict, List, Callable, Any


class MessageBus:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._subs: Dict[str, List[Callable]] = {}
        self._auth: Dict[str, set] = {}  # topic -> set of allowed agent ids

    def authorize_topic(self, topic: str, agents: List[str]):
        self._auth[topic] = set(agents)

    def subscribe(self, topic: str, agent_id: str, callback: Callable):
        if topic in self._auth and agent_id not in self._auth[topic]:
            raise PermissionError("topic access denied")
        self._subs.setdefault(topic, []).append(callback)

    def publish(self, topic: str, agent_id: str, message: Any):
        if topic in self._auth and agent_id not in self._auth[topic]:
            raise PermissionError("publish denied")
        for cb in self._subs.get(topic, []):
            cb(message)