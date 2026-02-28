"""Solana DeFi opportunity source.

Combines two data sources:
  1. DeFiLlama /pools — yields for Solana-chain pools (Orca, Raydium, Marinade, etc.)
  2. Jupiter Price API — real-time token prices for cross-DEX price gaps on Solana

Both are public, no auth required.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

DEFI_LLAMA_POOLS_URL = "https://yields.llama.fi/pools"
JUPITER_PRICE_URL = "https://price.jup.ag/v6/price"

SOLANA_CHAINS = {"Solana", "solana"}
MIN_TVL_USD = 500_000      # higher bar than Base; Solana pools are very liquid
MIN_APY = 5.0
MAX_POOL_RESULTS = 8

# Tokens to check for Jupiter cross-DEX arb opportunities
JUPITER_TOKENS = {
    "SOL":  "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "RAY":  "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "JUP":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
}


class SolanaDeFiSource(MarketSource):
    """Scans DeFiLlama for high-APY Solana pools."""

    name = "solana_defi"

    def __init__(self, min_apy: float = MIN_APY) -> None:
        self.min_apy = min_apy

    async def scan(self) -> Sequence[Opportunity]:
        pools = await self._fetch_pools()
        arb_opps = await self._fetch_jupiter_arb()
        return pools + arb_opps

    # ── DeFiLlama pools ───────────────────────────────────────────────────────

    async def _fetch_pools(self) -> list[Opportunity]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(DEFI_LLAMA_POOLS_URL)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("DeFiLlama Solana fetch failed: %s", exc)
            return []

        pools = data.get("data", [])
        candidates = [
            p for p in pools
            if p.get("chain") in SOLANA_CHAINS
            and (p.get("tvlUsd") or 0) >= MIN_TVL_USD
            and (p.get("apy") or 0) >= self.min_apy
        ]
        candidates.sort(key=lambda p: p.get("apy", 0), reverse=True)
        candidates = candidates[:MAX_POOL_RESULTS]

        opps = [self._pool_to_opp(p) for p in candidates]
        result = [o for o in opps if o is not None]
        logger.info("Solana DeFi: %d pool opportunities", len(result))
        return result

    def _pool_to_opp(self, pool: dict) -> Opportunity | None:
        try:
            pool_id = pool.get("pool", "")
            project = pool.get("project", "unknown")
            symbol = pool.get("symbol", "?")
            apy = float(pool.get("apy") or 0)
            tvl = float(pool.get("tvlUsd") or 0)

            # Weekly yield on a $100 position
            weekly_yield = Decimal("100") * Decimal(str(apy / 100 / 52))
            # Solana gas is extremely cheap (<$0.001 per tx typically)
            gas_estimate = Decimal("0.01")

            uid = hashlib.md5(pool_id.encode()).hexdigest()[:12]

            return Opportunity(
                id=f"sol_defi:{uid}",
                strategy_type=StrategyType.TRADE,
                title=f"[Solana] {project} {symbol} — {apy:.1f}% APY",
                description=(
                    f"Solana yield pool. Project: {project}, Symbol: {symbol}, "
                    f"APY: {apy:.2f}%, TVL: ${tvl:,.0f}. "
                    f"Gas cost ~$0.01 on Solana."
                ),
                expected_revenue_usdc=weekly_yield.quantize(Decimal("0.001")),
                estimated_cost_usdc=gas_estimate,
                effort_score=3.0,
                risk_score=min(10.0, max(1.0, 10 - apy / 10)),
                payload={
                    "chain": "solana",
                    "pool_id": pool_id,
                    "project": project,
                    "symbol": symbol,
                    "apy": apy,
                    "tvl_usd": tvl,
                },
            )
        except Exception as exc:
            logger.debug("Skipping Solana pool: %s", exc)
            return None

    # ── Jupiter price arb ────────────────────────────────────────────────────

    async def _fetch_jupiter_arb(self) -> list[Opportunity]:
        """Check if Jupiter quotes differ meaningfully from reference prices.

        Jupiter aggregates across all Solana DEXes (Orca, Raydium, Meteora,
        Phoenix, etc.) and provides the best swap quote. A large spread between
        input and output hint at arb opportunities across those venues.
        """
        try:
            ids = ",".join(JUPITER_TOKENS.values())
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    JUPITER_PRICE_URL,
                    params={"ids": ids},
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
        except Exception as exc:
            logger.debug("Jupiter price fetch failed: %s", exc)
            return []

        opps = []
        for name, mint in JUPITER_TOKENS.items():
            price_info = data.get(mint, {})
            if not price_info:
                continue

            price = float(price_info.get("price", 0))
            if price <= 0:
                continue

            # Confidence is the bid/ask spread as a fraction
            # A high confidence spread >0.3% can be profitable after Solana's ~$0.001 gas
            confidence = float(price_info.get("buyPrice", price) - price_info.get("sellPrice", price))
            spread_pct = abs(confidence / price * 100) if price else 0

            MIN_SPREAD = 0.3  # 0.3% minimum after fees
            if spread_pct < MIN_SPREAD:
                continue

            deploy = Decimal("100")
            gross = deploy * Decimal(str(spread_pct / 100))
            gas = Decimal("0.01")
            net = gross - gas

            if net <= 0:
                continue

            uid = hashlib.md5(f"jup:{name}:{price}".encode()).hexdigest()[:12]
            opps.append(Opportunity(
                id=f"sol_arb:{uid}",
                strategy_type=StrategyType.ARBITRAGE,
                title=f"[Solana] Jupiter {name}/USDC — {spread_pct:.2f}% spread",
                description=(
                    f"Jupiter aggregated price spread for {name}: {spread_pct:.3f}%. "
                    f"Buy/sell across Orca/Raydium/Meteora. Net on $100: ${float(net):.4f}."
                ),
                expected_revenue_usdc=net.quantize(Decimal("0.001")),
                estimated_cost_usdc=gas,
                effort_score=3.0,
                risk_score=5.0,
                payload={
                    "chain": "solana",
                    "token": name,
                    "mint": mint,
                    "price": price,
                    "spread_pct": spread_pct,
                    "venue": "jupiter",
                },
            ))

        logger.info("Solana Jupiter: %d arb opportunities", len(opps))
        return opps
