import os, json
from typing import Dict, Any, Optional

MANIFEST_SCHEMA_KEYS = {"name", "identity", "capabilities", "model", "memory", "tools", "permissions"}

# Permanent identity fields every agent manifest must declare. Identity is the
# immutable core of an agent; capabilities/tools/permissions/memory/model are the
# expandable surface and are intentionally kept out of this list. Missing or empty
# identity fields fail closed so an agent can never silently lose its identity.
REQUIRED_IDENTITY_FIELDS = (
    "display_name", "archetype", "role", "personality",
    "communication_style", "boundaries", "responsibilities",
    "decision_making", "signature_characteristics",
)


class AgentRegistry:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self._agents: Dict[str, Dict[str, Any]] = {}

    def load(self):
        if not os.path.isdir(self.base_dir):
            return
        for name in os.listdir(self.base_dir):
            mpath = os.path.join(self.base_dir, name, "manifest.json")
            if os.path.isfile(mpath):
                with open(mpath) as f:
                    m = json.load(f)
                if not MANIFEST_SCHEMA_KEYS.issubset(m.keys()):
                    raise ValueError(f"Invalid manifest for {name}: missing keys")
                identity = m.get("identity") or {}
                missing = [k for k in REQUIRED_IDENTITY_FIELDS
                           if not str(identity.get(k, "")).strip()]
                if missing:
                    raise ValueError(
                        f"Invalid agent identity for '{name}': missing or empty field(s) "
                        + ", ".join(missing)
                    )
                self._agents[m["name"]] = m

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(name)

    def list(self) -> list:
        return list(self._agents.keys())