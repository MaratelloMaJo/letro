"""Read-only investigation tools and a safe arithmetic calculator.

No shell, SQL, filesystem or network access exists here. Every returned value
is a copy, so an agent cannot mutate the episode state.
"""

from __future__ import annotations

import ast
import copy
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import Any

from .constants import MAX_PAGE, MAX_CALC_EXPRESSION_CHARS


class ToolError(ValueError):
    """Bounded, agent-visible tool error."""


SORT_KEYS = {
    "ledger": lambda row: row["row_id"],
    "invoices": lambda row: row["doc_id"],
    "payments": lambda row: row["doc_id"],
    "fx": lambda row: (row["date"], row["source_currency"], row["target_currency"]),
}


class OpenStore:
    def __init__(self, open_data: dict[str, Any]):
        self._data = copy.deepcopy(open_data)
        self._tables = {
            "ledger": sorted(self._data["ledger"], key=SORT_KEYS["ledger"]),
            "invoices": sorted(self._data["invoices"], key=SORT_KEYS["invoices"]),
            "payments": sorted(self._data["payments"], key=SORT_KEYS["payments"]),
            "fx": sorted(self._data["fx"], key=SORT_KEYS["fx"]),
        }
        self._documents: dict[str, dict[str, Any]] = {}
        for invoice in self._data["invoices"]:
            self._documents[invoice["doc_id"]] = invoice
            self._documents[invoice["invoice_id"]] = invoice
        for payment in self._data["payments"]:
            self._documents[payment["doc_id"]] = payment
            self._documents[payment["payment_id"]] = payment
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self._data["ledger"]:
            self._records[("ledger", row["row_id"])] = row
        for invoice in self._data["invoices"]:
            self._records[("invoices", invoice["doc_id"])] = invoice
            self._records[("invoices", invoice["invoice_id"])] = invoice
        for payment in self._data["payments"]:
            self._records[("payments", payment["doc_id"])] = payment
            self._records[("payments", payment["payment_id"])] = payment

    @property
    def manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["manifest"])

    @property
    def policy(self) -> dict[str, Any]:
        return copy.deepcopy(self._data["policy"])

    def list_records(
        self, table: str, cursor: int = 0, limit: int = MAX_PAGE
    ) -> dict[str, Any]:
        if table not in self._tables:
            raise ToolError("unknown table")
        if cursor < 0:
            raise ToolError("cursor must be non-negative")
        if limit < 1 or limit > MAX_PAGE:
            raise ToolError(f"limit must be between 1 and {MAX_PAGE}")
        rows = self._tables[table]
        page = rows[cursor : cursor + limit]
        next_cursor = cursor + len(page)
        return {
            "table": table,
            "cursor": cursor,
            "rows": copy.deepcopy(page),
            "next_cursor": next_cursor if next_cursor < len(rows) else None,
            "total": len(rows),
        }

    def get_record(self, table: str, record_id: str) -> dict[str, Any]:
        if table not in SORT_KEYS:
            raise ToolError("unknown table")
        found = self._records.get((table, record_id))
        if found is not None:
            return copy.deepcopy(found)
        if table == "fx":
            raise ToolError("fx rows have no record id; use list_records")
        raise ToolError("record not found")

    def get_document(self, doc_id: str) -> dict[str, Any]:
        found = self._documents.get(doc_id)
        if found is None:
            raise ToolError("document not found")
        return copy.deepcopy(found)


_ALLOWED_BINARY = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


def calculate(expression: str) -> str:
    if not isinstance(expression, str):
        raise ToolError("expression must be a string")
    text = expression.strip()
    if not text or len(text) > MAX_CALC_EXPRESSION_CHARS:
        raise ToolError("expression is empty or too long")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ToolError("expression is not valid arithmetic") from exc

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise ToolError("only decimal numbers are allowed")
            try:
                value = Decimal(str(node.value))
            except InvalidOperation as exc:
                raise ToolError("invalid number") from exc
            if not value.is_finite():
                raise ToolError("number must be finite")
            if abs(value.adjusted()) > 30:
                raise ToolError("number is out of range")
            return value
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINARY):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ToolError("division by zero")
            return left / right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        raise ToolError("only +, -, *, / and parentheses are allowed")

    try:
        with localcontext() as context:
            context.prec = 28
            result = evaluate(tree)
    except (DivisionByZero, InvalidOperation, OverflowError) as exc:
        raise ToolError("arithmetic error") from exc
    if not result.is_finite():
        raise ToolError("result must be finite")
    normalized = result.normalize()
    text_result = format(normalized, "f")
    if "." in text_result:
        text_result = text_result.rstrip("0").rstrip(".")
    return text_result or "0"


def dispatch(store: OpenStore, action: dict[str, Any]) -> dict[str, Any]:
    kind = action.get("type")
    if kind == "list_records":
        return store.list_records(
            action["table"], action.get("cursor", 0), action.get("limit", MAX_PAGE)
        )
    if kind == "get_record":
        return store.get_record(action["table"], action["id"])
    if kind == "get_document":
        return store.get_document(action["doc_id"])
    if kind == "calculator":
        return {"result": calculate(action["expression"])}
    raise ToolError("unknown action")
