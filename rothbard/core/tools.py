"""LangChain @tool wrappers available to the agent's LLM.

These are the actions the LLM can invoke during the select_strategy node
to gather information before making a decision.
"""
from __future__ import annotations

import logging

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
async def fetch_url(url: str) -> str:
    """Fetch the text content of any URL. Use for research."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # Return first 4000 chars to stay within context
            return resp.text[:4000]
    except Exception as exc:
        return f"Error fetching {url}: {exc}"


@tool
async def get_eth_gas_price() -> str:
    """Return current Ethereum/Base gas prices in gwei."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.etherscan.io/api?module=gastracker&action=gasoracle")
            resp.raise_for_status()
            data = resp.json().get("result", {})
            return (
                f"Safe: {data.get('SafeGasPrice')} gwei | "
                f"Standard: {data.get('ProposeGasPrice')} gwei | "
                f"Fast: {data.get('FastGasPrice')} gwei"
            )
    except Exception as exc:
        return f"Could not fetch gas price: {exc}"


@tool
async def search_defi_opportunities(min_apy: float = 10.0) -> str:
    """Search DeFiLlama for the highest APY pools on Base with at least min_apy%."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://yields.llama.fi/pools")
            resp.raise_for_status()
            pools = resp.json().get("data", [])

        base_pools = [
            p for p in pools
            if p.get("chain") in {"Base", "base"}
            and (p.get("apy") or 0) >= min_apy
            and (p.get("tvlUsd") or 0) >= 50_000
        ]
        base_pools.sort(key=lambda p: p.get("apy", 0), reverse=True)

        lines = []
        for p in base_pools[:5]:
            lines.append(
                f"• {p.get('project')} {p.get('symbol')}: "
                f"{p.get('apy', 0):.1f}% APY, TVL ${p.get('tvlUsd', 0):,.0f}"
            )
        return "\n".join(lines) if lines else "No pools found matching criteria."
    except Exception as exc:
        return f"Error: {exc}"


ALL_TOOLS = [fetch_url, get_eth_gas_price, search_defi_opportunities]
