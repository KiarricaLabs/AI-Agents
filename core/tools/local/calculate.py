"""`calculate` tool: safe, whitelisted arithmetic evaluator.

No eval/exec. Only numeric literals, the binary operators + - * / // % **,
unary +/-, and parentheses are permitted. Names, attribute access, calls,
subscripts, comprehensions, and strings are rejected. Result magnitude is
bounded to avoid unbounded computation.
"""
from __future__ import annotations

import ast
import math
import operator
from typing import Any, Optional

from core.tools import Tool

_MAX_EXPR_LEN = 200
_MAX_EXPONENT = 100
_MAX_INT_BITS = 1024

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculateTool(Tool):
    name = "calculate"
    description = (
        "Evaluate a deterministic arithmetic expression. Supports + - * / // % **, "
        "unary +/-, parentheses, and numeric literals only."
    )
    consequential = False

    def run(self, args: Optional[dict] = None, context: Optional[dict] = None) -> Any:
        args = args or {}
        expr = args.get("expression", args.get("expr"))
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError("calculate requires a non-empty 'expression' string")
        expr = expr.strip()
        if len(expr) > _MAX_EXPR_LEN:
            raise ValueError("expression exceeds 200 characters")

        tree = ast.parse(expr, mode="eval")
        value = self._eval(tree.body)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("result must be numeric")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("result is not finite")
        return value

    def _eval(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("unsupported constant")
            return node.value

        if isinstance(node, ast.BinOp):
            fn = _BIN_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("unsupported operator")
            left = self._eval(node.left)
            right = self._eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
                raise ValueError("exponent magnitude exceeds 100")
            return self._guard(fn(left, right))

        if isinstance(node, ast.UnaryOp):
            fn = _UNARY_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("unsupported unary operator")
            return self._guard(fn(self._eval(node.operand)))

        raise ValueError("unsupported expression")

    def _guard(self, value):
        if isinstance(value, bool):
            raise ValueError("result must be numeric")
        if isinstance(value, int):
            if value.bit_length() > _MAX_INT_BITS:
                raise ValueError("integer result too large")
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("result is not finite")
            return value
        raise ValueError("result must be numeric")
