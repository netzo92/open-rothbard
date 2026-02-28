"""RothbardAgent — builds and returns the compiled LangGraph.

Graph topology:
  check_treasury
    → scan_markets
      → rank_opportunities
        → select_strategy
          → [execute_strategy | idle]  (conditional)
            → update_memory
              → idle  (always)
                → check_treasury  (loop)
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from rothbard.core.edges import route_after_execute, route_after_select
from rothbard.core.nodes import (
    check_treasury,
    execute_strategy,
    idle,
    rank_opportunities,
    scan_markets,
    select_strategy,
    update_memory,
)
from rothbard.core.state import AgentState


def build_graph():
    """Build and compile the agent graph. Returns a runnable."""
    g = StateGraph(AgentState)

    # Register nodes
    g.add_node("check_treasury", check_treasury)
    g.add_node("scan_markets", scan_markets)
    g.add_node("rank_opportunities", rank_opportunities)
    g.add_node("select_strategy", select_strategy)
    g.add_node("execute_strategy", execute_strategy)
    g.add_node("update_memory", update_memory)
    g.add_node("idle", idle)

    # Entry point
    g.set_entry_point("check_treasury")

    # Linear flow up to decision point
    g.add_edge("check_treasury", "scan_markets")
    g.add_edge("scan_markets", "rank_opportunities")
    g.add_edge("rank_opportunities", "select_strategy")

    # Conditional: execute or idle
    g.add_conditional_edges(
        "select_strategy",
        route_after_select,
        {"execute_strategy": "execute_strategy", "idle": "idle"},
    )

    # After execution: always update memory
    g.add_edge("execute_strategy", "update_memory")

    # After memory update: idle (throttle), then loop
    g.add_edge("update_memory", "idle")

    # Loop back
    g.add_edge("idle", "check_treasury")

    return g.compile()


class RothbardAgent:
    """High-level wrapper around the compiled graph."""

    def __init__(self) -> None:
        self.graph = build_graph()

    async def run(self) -> None:
        """Run the agent loop indefinitely."""
        from decimal import Decimal

        initial_state: AgentState = {
            "cycle": 0,
            "treasury_balance": Decimal("0"),
            "opportunities": [],
            "selected_strategy": None,
            "active_workers": [],
            "last_action": "starting up",
            "messages": [],
            "errors": [],
        }
        # stream=True gives us node-by-node updates; we run until interrupted
        async for event in self.graph.astream(initial_state, stream_mode="updates"):
            node_name = list(event.keys())[0] if event else "?"
            # Logging is handled within each node
            _ = node_name
