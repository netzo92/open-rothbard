"""Working memory helpers — convenience accessors for AgentState."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rothbard.core.state import AgentState


def get_balance(state: "AgentState") -> Decimal:
    return state.get("treasury_balance", Decimal("0"))


def set_balance(state: "AgentState", balance: Decimal) -> dict:
    return {"treasury_balance": balance}


def add_error(state: "AgentState", error: str) -> dict:
    errors = list(state.get("errors", []))
    errors.append(error)
    return {"errors": errors}


def clear_errors(state: "AgentState") -> dict:
    return {"errors": []}


def increment_cycle(state: "AgentState") -> dict:
    return {"cycle": state.get("cycle", 0) + 1}
