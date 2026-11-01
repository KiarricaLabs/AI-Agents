import os, json
from typing import Dict, Any, Optional

MANIFEST_SCHEMA_KEYS = {"name", "identity", "capabilities", "model", "memory", "tools", "permissions"}


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
                self._agents[m["name"]] = m

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(name)

    def list(self) -> list:
        return list(self._agents.keys())