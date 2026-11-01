"""Policy enforcement wrapper: default deny."""
from __future__ import annotations
from core.policy import PolicyEngine


class PolicyEnforcer:
    def __init__(self, engine: PolicyEngine):
        self.engine = engine

    def check(self, subject, action, resource):
        if not self.engine.allow(subject, action, resource):
            raise PermissionError("policy denied")