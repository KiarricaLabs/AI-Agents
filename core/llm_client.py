"""Provider-agnostic LLM client. No cloud credentials required for local (Ollama)."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from config.settings import AI_PROVIDER, AI_MODEL, AI_BASE_URL, AI_API_KEY


class LLMClient:
    def __init__(self, provider=None, model=None, base_url=None, api_key=None):
        self.provider = (provider or AI_PROVIDER).lower()
        self.model = model or AI_MODEL
        self.base_url = base_url or AI_BASE_URL
        self.api_key = api_key if api_key is not None else AI_API_KEY

    def complete(self, prompt: str, system: str = "", timeout: int = 120, format_json: bool = False) -> str:
        if self.provider == "ollama":
            payload = {"model": self.model, "prompt": prompt, "system": system, "stream": False}
            if format_json:
                # Ollama JSON mode: constrain the model to emit a JSON object.
                payload["format"] = "json"
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return data.get("response", "").strip()
        # Cloud providers require explicit api_key; fail loudly if missing
        if not self.api_key:
            raise RuntimeError(f"Provider {self.provider} requires API key; none configured.")
        return f"[{self.provider} not implemented in M0]"


def build_client(provider=None, model=None, base_url=None, api_key=None):
    return LLMClient(provider, model, base_url, api_key)