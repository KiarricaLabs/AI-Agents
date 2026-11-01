"""Provider-agnostic model router. Local-first; Ollama is the only active provider (M8).

Design goals:
- One routing interface for all agents; per-agent `model` spec comes from the manifest.
- Local inference is the default; there is NO silent cloud fallback.
- Every execution reports a `location` string describing where data was processed.
- Bounded retry/timeout on transient failures — retries stay within the same local provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.settings import AI_PROVIDER, AI_MODEL, AI_BASE_URL


@dataclass
class ModelResult:
    text: str
    provider: str
    model: str
    location: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "location": self.location,
        }


class ModelRouter:
    """Resolves an agent's model preference and executes it locally (Ollama)."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 120, retries: int = 2):
        self.base_url = base_url or AI_BASE_URL
        self.timeout = timeout
        self.retries = retries

    def complete(
        self,
        agent_id: str,
        prompt: str,
        system: str = "",
        model_spec: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ModelResult:
        from core.tracing import start_span, end_span
        from core import metrics

        span = start_span("model_router.complete", {"agent": agent_id})
        try:
            provider, model = self._resolve(model_spec)
            if provider != "ollama":
                # No silent cloud routing or fallback: fail loudly.
                raise RuntimeError(
                    f"Provider '{provider}' is not available in M8 (local-only Ollama). "
                    "No cloud routing or fallback is enabled."
                )
            text = self._generate_with_retry(model, prompt, system)
            location = f"local:{provider}:{model}"
            result = ModelResult(text=text, provider=provider, model=model, location=location)
            span["attrs"]["location"] = location
            span["attrs"]["status"] = "ok"
            metrics.inc("model_call_total", {"provider": provider, "agent": agent_id})
            end_span(span)
            return result
        except Exception as e:
            span["attrs"]["status"] = "error"
            span["attrs"]["error"] = type(e).__name__
            metrics.inc("model_call_errors_total", {"agent": agent_id})
            end_span(span)
            raise

    def _resolve(self, model_spec: Optional[Dict[str, Any]]):
        spec = model_spec or {}
        provider = str(spec.get("provider") or AI_PROVIDER).lower()
        model = spec.get("model") or AI_MODEL
        return provider, model

    def _generate_with_retry(self, model: str, prompt: str, system: str) -> str:
        last_err: Optional[Exception] = None
        for _attempt in range(self.retries):
            try:
                return self._generate_once(model, prompt, system)
            except (OSError, TimeoutError) as e:
                last_err = e
        raise RuntimeError(
            f"Ollama generation failed after {self.retries} attempts: {last_err}"
        )

    def _generate_once(self, model: str, prompt: str, system: str) -> str:
        from core.llm_client import LLMClient

        client = LLMClient(provider="ollama", model=model, base_url=self.base_url)
        return client.complete(prompt, system, timeout=self.timeout)
