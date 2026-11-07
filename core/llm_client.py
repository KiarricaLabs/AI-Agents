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

    def complete(self, prompt: str, system: str = "", timeout: int = 120,
                 format_json: bool = False, json_schema: Optional[dict] = None) -> str:
        if self.provider == "ollama":
            # keep_alive keeps the model resident across a multi-step run, avoiding
            # the ~20-25s reload warmup on every agent call. num_ctx is set high so
            # long prompts (business profile + task + dependency outputs) are not
            # truncated, which also avoids reprocessing/truncated drafts.
            keep_alive = os.getenv("PAT_LLM_KEEP_ALIVE", "30m")
            num_ctx = int(os.getenv("PAT_LLM_NUM_CTX", "8192") or "8192")
            options = {"num_ctx": num_ctx}
            payload = {"model": self.model, "prompt": prompt, "system": system,
                       "stream": False, "keep_alive": keep_alive, "options": options}
            if json_schema is not None:
                payload["format"] = json_schema
                options["temperature"] = 0
                options["num_predict"] = 1600
            elif format_json:
                # Ollama JSON mode: constrain the model to emit a JSON object.
                payload["format"] = "json"
            else:
                # Free-form draft/executor path: low temperature for coherent,
                # on-brief output, with a generous token budget for multi-section
                # drafts; both are configurable.
                options["temperature"] = float(os.getenv("PAT_LLM_TEMPERATURE", "0.3") or "0.3")
                options["num_predict"] = int(os.getenv("PAT_LLM_NUM_PREDICT", "1800") or "1800")
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

    def ping(self, timeout: float = 3.0) -> bool:
        """Lightweight, non-generative availability probe (Ollama /api/tags).

        Never creates any conversation history or workspace state. Raises on
        unreachable/unavailable Ollama (callers map to a safe status).
        """
        if self.provider != "ollama":
            return False
        req = urllib.request.Request(f"{self.base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout):
            return True


def build_client(provider=None, model=None, base_url=None, api_key=None):
    return LLMClient(provider, model, base_url, api_key)
