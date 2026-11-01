"""Local-only built-in tools for Phase C.

Deterministic, offline, permission-gated, sandboxed. No eval/exec/subprocess,
no network, no unrestricted filesystem access.
"""
from core.tools.local.now import NowTool
from core.tools.local.calculate import CalculateTool

__all__ = ["NowTool", "CalculateTool"]
