"""AgentState — the shared state object flowing through the LangGraph."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from rothbard.markets.sources.base import Opportunity


class WorkerInfo(TypedDict):
    container_id: str
    task_id: str
    strategy: str
    started_at: str
    budget_usdc: str


class AgentState(TypedDict):
    # Loop counter
    cycle: int

    # Current wallet balance in USDC
    treasury_balance: Decimal

    # Opportunities discovered in the latest scan
    opportunities: list[Opportunity]

    # Strategy the LLM selected for this cycle (or None/wait)
    selected_strategy: str | None

    # Active worker containers spawned this cycle
    active_workers: list[WorkerInfo]

    # Summary of the last completed action
    last_action: str

    # LLM message history (append-only via add_messages)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Errors collected during this cycle
    errors: list[str]
