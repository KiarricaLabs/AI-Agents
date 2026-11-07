"""Provider-agnostic model router. Local-first; Ollama is the only active provider (M8).

Design goals:
- One routing interface for all agents; per-agent `model` spec comes from the manifest.
- Local inference is the default; there is NO silent cloud fallback.
- Every execution reports a `location` string describing where data was processed.
- Bounded retry/timeout on transient failures — retries stay within the same local provider.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from config.settings import AI_PROVIDER, AI_MODEL, AI_BASE_URL
from core.errors import ModelUnavailableError, ModelEmptyOutputError


# Opt-in deterministic mock for testing agent responses WITHOUT a live model.
# Only active when PAT_MOCK_AGENTS is set (1/true/yes). Never the default and
# never used for real work; replies are labelled location=\"mock\" so they can't
# be mistaken for model output. Fail-closed: absent the flag, real Ollama runs.
def _mock_enabled() -> bool:
    return (os.environ.get("PAT_MOCK_AGENTS") or "").lower() in ("1", "true", "yes")


MOCK_REPLIES: Dict[str, str] = {
    "workspace_architect": "Here is the workspace-architect view of that request — scope, responsibilities, and the structure I'd recommend.",
    "strategist": "From the strategist seat: here is a concise recommendation and the tradeoffs worth weighing before we proceed.",
    "tutor": "As tutor, here is a clear explanation of the idea, the steps involved, and what each one builds toward.",
    "executive_assistant": "As your assistant, here is a tidy summary of what's being asked, what happens next, and what needs your go-ahead.",
    "communications": "Here is a draft comms angle for the request — clear messaging you could review and refine.",
    "soundboard": "Here are a few perspectives worth considering on that request, as an honest sounding board.",
}


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
        json_format: bool = False,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> ModelResult:
        # OPT-IN deterministic mock (testing agent responses without a live model).
        if _mock_enabled():
            return ModelResult(
                text=MOCK_REPLIES.get(agent_id, MOCK_REPLIES["workspace_architect"]),
                provider="mock", model="mock", location="mock",
            )
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
            text = self._generate_with_retry(
                model, prompt, system, json_format=json_format, json_schema=json_schema)
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
        # A1: allow a faster execution model via env without changing manifests.
        exec_override = os.getenv("PAT_EXEC_MODEL")
        if exec_override and spec.get("role") != "planner":
            model = exec_override
        return provider, model

    def _generate_with_retry(self, model: str, prompt: str, system: str,
                             json_format: bool = False,
                             json_schema: Optional[Dict[str, Any]] = None) -> str:
        last_err: Optional[Exception] = None
        for _attempt in range(self.retries):
            try:
                if json_format:
                    text = self._generate_once(
                        model, prompt, system, json_format=True, json_schema=json_schema)
                else:
                    if json_schema is not None:
                        text = self._generate_once(model, prompt, system, json_schema=json_schema)
                    else:
                        text = self._generate_once(model, prompt, system)
                # Empty/whitespace-only output is a failure, never a successful
                # reply; it is retried within the bounded window.
                if not text or not text.strip():
                    raise ModelEmptyOutputError("model returned empty output")
                return text
            except (OSError, TimeoutError, ModelEmptyOutputError) as e:
                # Connectivity/timeout and empty output are all retried within
                # the bounded window, staying on the same local provider.
                last_err = e
        if isinstance(last_err, ModelEmptyOutputError):
            raise ModelEmptyOutputError(
                "Ollama returned empty output after retries"
            ) from None
        raise ModelUnavailableError(
            f"Ollama generation failed after {self.retries} attempts"
        ) from None

    def _generate_once(self, model: str, prompt: str, system: str,
                       json_format: bool = False,
                       json_schema: Optional[Dict[str, Any]] = None) -> str:
        from core.llm_client import LLMClient

        client = LLMClient(provider="ollama", model=model, base_url=self.base_url)
        if json_schema is not None:
            return client.complete(prompt, system, timeout=self.timeout, json_schema=json_schema)
        if json_format:
            return client.complete(prompt, system, timeout=self.timeout, format_json=True)
        return client.complete(prompt, system, timeout=self.timeout)

    def check_availability(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Non-generative, read-only model-health probe.

        Attempts a short, bounded call to Ollama (/api/tags). Never creates
        conversation history or workspace state. Returns a safe status dict;
        on failure the code is ``model_unavailable`` with no raw internals.
        """
        provider, model = self._resolve(None)
        probe_timeout = timeout if timeout is not None else min(3.0, self.timeout)
        available = False
        try:
            from core.llm_client import LLMClient

            client = LLMClient(provider="ollama", model=model, base_url=self.base_url)
            available = bool(client.ping(timeout=probe_timeout))
        except Exception:
            available = False
        return {
            "ok": available,
            "available": available,
            "provider": provider,
            "model": model,
            "location": f"local:{provider}:{model}",
            "code": "ok" if available else "model_unavailable",
        }
