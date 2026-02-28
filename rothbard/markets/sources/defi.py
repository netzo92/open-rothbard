"""DeFi yield opportunity source — powered by DeFiLlama API.

Polls https://yields.llama.fi/pools for the highest APY pools on Base
network and converts them into Opportunity objects.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

DEFI_LLAMA_URL = "https://yields.llama.fi/pools"
TARGET_CHAINS = {"Base", "base"}
MIN_TVL_USD = 100_000  # ignore micro-pools with <$100k TVL
MAX_RESULTS = 10


class DeFiYieldSource(MarketSource):
    """Scans DeFiLlama for high-APY pools on Base network."""

    name = "defi_yield"

    def __init__(self, min_apy: float = 5.0) -> None:
        self.min_apy = min_apy

    async def scan(self) -> Sequence[Opportunity]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(DEFI_LLAMA_URL)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("DeFiLlama fetch failed: %s", exc)
            return []

        pools = data.get("data", [])
        # Filter: Base chain, minimum TVL, positive APY, no stablecoin-only boring yields
        candidates = [
            p for p in pools
            if p.get("chain") in TARGET_CHAINS
            and (p.get("tvlUsd") or 0) >= MIN_TVL_USD
            and (p.get("apy") or 0) >= self.min_apy
        ]

        # Sort by APY descending, take top N
        candidates.sort(key=lambda p: p.get("apy", 0), reverse=True)
        candidates = candidates[:MAX_RESULTS]

        opportunities = []
        for pool in candidates:
            opp = self._pool_to_opportunity(pool)
            if opp:
                opportunities.append(opp)

        logger.info("DeFi scanner found %d opportunities", len(opportunities))
        return opportunities

    def _pool_to_opportunity(self, pool: dict) -> Opportunity | None:
        try:
            pool_id = pool.get("pool", "")
            project = pool.get("project", "unknown")
            symbol = pool.get("symbol", "?")
            apy = float(pool.get("apy") or 0)
            tvl = float(pool.get("tvlUsd") or 0)

            # Estimate: if we deploy $100 USDC for 1 week at this APY
            weekly_revenue = Decimal("100") * Decimal(str(apy / 100 / 52))
            gas_estimate = Decimal("0.50")  # Base gas is cheap

            uid = hashlib.md5(pool_id.encode()).hexdigest()[:12]

            return Opportunity(
                id=f"defi:{uid}",
                strategy_type=StrategyType.TRADE,
                title=f"{project} {symbol} — {apy:.1f}% APY",
                description=(
                    f"Yield farming pool on Base. Project: {project}, "
                    f"Symbol: {symbol}, APY: {apy:.2f}%, TVL: ${tvl:,.0f}"
                ),
                expected_revenue_usdc=weekly_revenue.quantize(Decimal("0.01")),
                estimated_cost_usdc=gas_estimate,
                effort_score=3.0,
                risk_score=min(10.0, max(1.0, 10 - apy / 10)),  # higher APY = higher risk
                payload={
                    "pool_id": pool_id,
                    "project": project,
                    "symbol": symbol,
                    "apy": apy,
                    "tvl_usd": tvl,
                    "chain": pool.get("chain"),
                },
            )
        except Exception as exc:
            logger.debug("Skipping pool due to parse error: %s", exc)
            return None
