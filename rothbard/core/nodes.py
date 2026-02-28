"""LangGraph node functions — each node is an async function that
receives the current AgentState and returns a partial state update.
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from rothbard.config import settings
from rothbard.core.state import AgentState
from rothbard.core.tools import ALL_TOOLS
from rothbard.finance.treasury import LedgerCategory, Treasury
from rothbard.finance.wallet import Wallet
from rothbard.markets.scanner import OpportunityScanner
from rothbard.memory import episodic, semantic
from rothbard.revenue.registry import get_all_strategies

logger = logging.getLogger(__name__)

# Shared singletons (set up in main.py before graph runs)
_wallet: Wallet | None = None
_treasury: Treasury | None = None
_scanner: OpportunityScanner | None = None


def setup(wallet: Wallet, treasury: Treasury, scanner: OpportunityScanner) -> None:
    global _wallet, _treasury, _scanner
    _wallet = wallet
    _treasury = treasury
    _scanner = scanner


# ── nodes ─────────────────────────────────────────────────────────────────────


async def check_treasury(state: AgentState) -> dict:
    """Fetch current wallet balance and update state."""
    balance = await _wallet.get_balance() if _wallet else Decimal("0")
    logger.info("[cycle %d] Treasury: %s USDC", state["cycle"], balance)
    return {"treasury_balance": balance}


async def scan_markets(state: AgentState) -> dict:
    """Discover opportunities from all market sources."""
    balance = state.get("treasury_balance", Decimal("0"))
    opportunities = await _scanner.scan_all(available_usdc=balance)
    logger.info("[cycle %d] Found %d opportunities", state["cycle"], len(opportunities))
    return {"opportunities": opportunities}


async def rank_opportunities(state: AgentState) -> dict:
    """Opportunities are already ranked by scanner; enrich with semantic recall."""
    opps = state.get("opportunities", [])

    # Recall relevant past experiences for the top opportunities
    enriched = []
    for opp in opps[:5]:
        memories = await semantic.recall(opp.title, n_results=3)
        if memories:
            mem_text = " | ".join(m["text"][:100] for m in memories)
            opp.description += f"\n[Memory: {mem_text}]"
        enriched.append(opp)

    return {"opportunities": enriched + opps[5:]}


async def select_strategy(state: AgentState) -> dict:
    """LLM selects which strategy to execute (or 'wait')."""
    cycle = state["cycle"]
    balance = state.get("treasury_balance", Decimal("0"))
    opps = state.get("opportunities", [])[:5]  # show top 5 to LLM

    opp_text = "\n".join(
        f"{i+1}. [{o.strategy_type}] {o.title} | "
        f"ROI: ${float(o.expected_roi):.2f} | Risk: {o.risk_score}/10\n   {o.description[:200]}"
        for i, o in enumerate(opps)
    ) if opps else "No opportunities found."

    llm = ChatAnthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
    ).bind_tools(ALL_TOOLS)

    system = SystemMessage(content=(
        "You are an autonomous economic agent named Rothbard. "
        "Your goal is to grow your USDC treasury through voluntary market participation. "
        "Evaluate the available opportunities and choose the best action for this cycle. "
        "Respond with a JSON object: {\"strategy\": \"trade|freelance|arbitrage|content|wait\", "
        "\"opportunity_id\": \"<id or null>\", \"reasoning\": \"<1-2 sentences>\"}"
    ))
    human = HumanMessage(content=(
        f"Cycle {cycle} | Treasury: {balance} USDC\n\n"
        f"Available opportunities:\n{opp_text}\n\n"
        "Choose the best strategy for this cycle."
    ))

    messages = [system, human]
    response = await llm.ainvoke(messages)

    # Parse JSON from response
    try:
        content = response.content
        # Extract JSON block if wrapped in markdown
        if "```" in content:
            content = content.split("```")[1].replace("json", "").strip()
        decision = json.loads(content)
        chosen = decision.get("strategy", "wait")
        opp_id = decision.get("opportunity_id")
        reasoning = decision.get("reasoning", "")
    except Exception:
        chosen = "wait"
        opp_id = None
        reasoning = "Failed to parse LLM decision, defaulting to wait."

    logger.info("[cycle %d] Strategy selected: %s | %s", cycle, chosen, reasoning)

    # Find the selected opportunity object
    selected_opp = None
    if opp_id:
        selected_opp = next((o for o in opps if o.id == opp_id), None)
    if not selected_opp and opps and chosen != "wait":
        # Fall back to top opportunity of the chosen type
        selected_opp = next(
            (o for o in opps if o.strategy_type == chosen), opps[0] if opps else None
        )

    return {
        "selected_strategy": chosen,
        "opportunities": ([selected_opp] if selected_opp else []),
        "messages": [system, human, response],
        "last_action": f"Selected strategy: {chosen} — {reasoning}",
    }


async def execute_strategy(state: AgentState) -> dict:
    """Dispatch to the appropriate revenue strategy plugin."""
    strategy_name = state.get("selected_strategy")
    opps = state.get("opportunities", [])
    opp = opps[0] if opps else None

    if not strategy_name or strategy_name == "wait" or not opp:
        return {"last_action": "No strategy executed (wait)"}

    strategies = {s.name: s for s in get_all_strategies()}
    strategy = strategies.get(strategy_name)

    if not strategy:
        return {"errors": [f"Unknown strategy: {strategy_name}"], "last_action": "Strategy not found"}

    try:
        result = await strategy.execute(opp, _wallet)
        if result.success:
            await _treasury.record_income(
                LedgerCategory(f"income:{strategy_name}"),
                result.profit_usdc,
                details=result.details,
                strategy=strategy_name,
            )
        return {
            "last_action": f"Executed {strategy_name}: {result.details}",
            "errors": [] if result.success else [result.details],
        }
    except Exception as exc:
        logger.error("Strategy %s failed: %s", strategy_name, exc)
        return {
            "last_action": f"Strategy {strategy_name} crashed",
            "errors": [str(exc)],
        }


async def update_memory(state: AgentState) -> dict:
    """Persist this cycle's outcome to episodic and semantic memory."""
    cycle = state["cycle"]
    strategy = state.get("selected_strategy") or "none"
    action = state.get("last_action", "")
    errors = state.get("errors", [])
    outcome = "failure" if errors else "success"
    opps = state.get("opportunities", [])

    await episodic.record_episode(
        cycle=cycle,
        strategy=strategy,
        action=action[:128],
        outcome=outcome,
        details="; ".join(errors) if errors else "",
    )

    if opps:
        opp = opps[0]
        await semantic.store_opportunity_outcome(
            opportunity_type=str(opp.strategy_type),
            description=opp.title,
            outcome=outcome,
            profit_usdc="0",  # actual P&L tracked in treasury
            cycle=cycle,
        )

    return {}


async def idle(state: AgentState) -> dict:
    """Wait for the configured scan interval before the next cycle."""
    wait_seconds = settings.scan_interval_minutes * 60
    logger.info("Idle — next cycle in %d minutes", settings.scan_interval_minutes)
    await asyncio.sleep(wait_seconds)
    return {"cycle": state["cycle"] + 1, "errors": [], "active_workers": []}
