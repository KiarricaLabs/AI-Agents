"""Stable, machine-readable error taxonomy for AI generation and retrieval.

All exceptions subclass :class:`RuntimeError` so existing handlers that treat
generation/provider failures as ``RuntimeError`` keep working as a fallback.
Each type carries a stable ``code`` and ``retryable`` flag the API and frontend
can rely on. No exception here ever carries raw connection internals, stack
traces, or sensitive values — messages are safe, human-readable text.
"""
from __future__ import annotations


class GenerationError(RuntimeError):
    """Base class for generation/retrieval failures surfaced to the user."""

    code = "model_unavailable"
    retryable = True


class ModelUnavailableError(GenerationError):
    """The language model could not be reached (down, refused, timeout).

    Connectivity and timeout failures are normalized to this single category
    because the frontend does not need to distinguish them. No cloud fallback
    exists; retries stay within the same local provider.
    """

    code = "model_unavailable"
    retryable = True


class ModelEmptyOutputError(GenerationError):
    """The model returned empty or whitespace-only output.

    Empty generation is a failure, never a successful reply.
    """

    code = "model_empty"
    retryable = True


class MemoryRetrievalError(GenerationError):
    """Saved context (memory/brand) could not be retrieved or read.

    We never invent memories and never proceed as though unavailable context
    was successfully loaded.
    """

    code = "memory_error"
    retryable = True
