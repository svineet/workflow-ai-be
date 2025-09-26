from __future__ import annotations

import ast
import operator
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


# Safe eval adapted: allow numbers and basic arithmetic operations only
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Num,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Load,
    ast.Constant,
)

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def safe_eval(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("Disallowed expression")
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants allowed")
        if isinstance(node, ast.Num):  # py<3.8 compatibility
            return float(node.n)
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            raise ValueError("Unsupported unary op")
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            if op_type in _OPERATORS:
                return float(_OPERATORS[op_type](left, right))
            raise ValueError("Unsupported operator")
        raise ValueError("Unsupported expression")
    return float(_eval(tree))


class CalcSettings(BaseModel):
    expression: Optional[str] = Field(default=None, description="Arithmetic expression, e.g., '2 + 2 * 3'. Optional when invoked as a tool with runtime input.")


class CalcOutput(BaseModel):
    result: float


@register("tool.calculator")
class CalculatorBlock(Block):
    type_name = "tool.calculator"
    summary = "Calculator tool: evaluate basic arithmetic expressions"
    settings_model = CalcSettings
    output_model = CalcOutput
    tool_compatible = True  # hint for UIs

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {"toolCompatible": True}

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        expr = (self.settings or {}).get("expression")
        if not expr:
            # Allow passing expression via runtime trigger or upstream for agent tool usage
            upstream = input.get("upstream") or {}
            trigger = input.get("trigger") or {}
            # Common places: trigger.prompt, trigger.input, or upstream values
            candidate = None
            try:
                candidate = trigger.get("expression") or trigger.get("input") or trigger.get("prompt")
            except Exception:
                candidate = None
            if candidate is None and upstream:
                # Try first upstream value string
                try:
                    first_key = next(iter(upstream.keys()))
                    first_val = upstream.get(first_key)
                    candidate = str(first_val)
                except Exception:
                    candidate = None
            expr = candidate
        if not expr:
            raise ValueError("tool.calculator requires 'expression'")
        node_id = input.get("node_id")
        await ctx.logger("tool.calculator: evaluating", {"expression": expr}, node_id=node_id)
        val = safe_eval(str(expr))
        return CalcOutput(result=val).model_dump() 