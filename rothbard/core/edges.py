"""Conditional edge router functions for the LangGraph."""
from __future__ import annotations

from rothbard.core.state import AgentState


def route_after_select(state: AgentState) -> str:
    """Route to the correct execution node based on selected strategy."""
    strategy = state.get("selected_strategy") or "wait"

    if strategy in {"trade", "freelance", "arbitrage", "content"}:
        return "execute_strategy"

    return "idle"


def route_after_execute(state: AgentState) -> str:
    """After execution, always update memory then loop."""
    return "update_memory"
