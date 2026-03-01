"""Cross-exchange price arbitrage opportunity source.

Compares asset prices across public DEX APIs and CEX public endpoints.
Currently checks ETH/USDC price across Uniswap V3 (Base) and Coinbase spot.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

# Minimum price gap % to consider worth executing after gas/fees
MIN_GAP_PCT = 0.5
# Coinbase public price API (no auth required)
CB_PRICE_URL = "https://api.coinbase.com/v2/prices/{pair}/spot"
# DeFiLlama coins price API — aggregates prices across DEXes
DEFILLAMA_PRICE_URL = "https://coins.llama.fi/prices/current/{coins}"

# Maps asset symbol → CoinGecko ID used by DeFiLlama
COINGECKO_IDS = {
    "ETH": "coingecko:ethereum",
    "BTC": "coingecko:bitcoin",
    "SOL": "coingecko:solana",
}

PAIRS = [
    {"base": "ETH", "quote": "USDC"},
    {"base": "SOL", "quote": "USDC"},
]


class ArbitrageSource(MarketSource):
    """Detects price gaps between DEXes and CEXes."""

    name = "arbitrage"

    async def scan(self) -> Sequence[Opportunity]:
        opportunities = []
        for pair in PAIRS:
            opp = await self._check_pair(pair)
            if opp:
                opportunities.append(opp)
        return opportunities

    async def _check_pair(self, pair: dict) -> Opportunity | None:
        base, quote = pair["base"], pair["quote"]
        try:
            cex_price, dex_price = await self._fetch_prices(base, quote)
            if cex_price is None or dex_price is None:
                return None

            gap_pct = abs(cex_price - dex_price) / min(cex_price, dex_price) * 100

            if gap_pct < MIN_GAP_PCT:
                return None

            # Estimate profit on $100 arb
            capital = Decimal("100")
            gross_profit = capital * Decimal(str(gap_pct / 100))
            gas_cost = Decimal("1.00")
            net_profit = gross_profit - gas_cost

            if net_profit <= 0:
                return None

            uid = hashlib.md5(f"{base}{quote}{cex_price}{dex_price}".encode()).hexdigest()[:12]
            buy_on = "dex" if dex_price < cex_price else "cex"
            sell_on = "cex" if buy_on == "dex" else "dex"

            return Opportunity(
                id=f"arb:{uid}",
                strategy_type=StrategyType.ARBITRAGE,
                title=f"{base}/{quote} arb — {gap_pct:.2f}% gap",
                description=(
                    f"Buy {base} on {buy_on.upper()} at {min(cex_price, dex_price):.2f}, "
                    f"sell on {sell_on.upper()} at {max(cex_price, dex_price):.2f}. "
                    f"Gap: {gap_pct:.2f}%, estimated net profit on $100: ${float(net_profit):.2f}"
                ),
                expected_revenue_usdc=net_profit.quantize(Decimal("0.01")),
                estimated_cost_usdc=gas_cost,
                effort_score=4.0,
                risk_score=6.0,  # execution risk: gap may close
                payload={
                    "base": base,
                    "quote": quote,
                    "cex_price": float(cex_price),
                    "dex_price": float(dex_price),
                    "gap_pct": gap_pct,
                    "buy_on": buy_on,
                    "sell_on": sell_on,
                },
            )
        except Exception as exc:
            logger.warning("Arbitrage check failed for %s/%s: %s", base, quote, exc)
            return None

    async def _fetch_prices(
        self, base: str, quote: str
    ) -> tuple[Decimal | None, Decimal | None]:
        async with httpx.AsyncClient(timeout=10) as client:
            cex_price = await self._coinbase_price(client, base, quote)
            dex_price = await self._defilama_price(client, base)
        return cex_price, dex_price

    async def _coinbase_price(
        self, client: httpx.AsyncClient, base: str, quote: str
    ) -> Decimal | None:
        try:
            url = CB_PRICE_URL.format(pair=f"{base}-{quote}")
            resp = await client.get(url)
            resp.raise_for_status()
            amount = resp.json()["data"]["amount"]
            return Decimal(amount)
        except Exception as exc:
            logger.debug("Coinbase price fetch failed: %s", exc)
            return None

    async def _defilama_price(
        self, client: httpx.AsyncClient, base: str
    ) -> Decimal | None:
        """Fetch aggregated DEX price from DeFiLlama coins API."""
        coin_id = COINGECKO_IDS.get(base)
        if not coin_id:
            return None
        try:
            url = DEFILLAMA_PRICE_URL.format(coins=coin_id)
            resp = await client.get(url)
            resp.raise_for_status()
            price = resp.json()["coins"][coin_id]["price"]
            return Decimal(str(price))
        except Exception as exc:
            logger.debug("DeFiLlama price fetch failed for %s: %s", base, exc)
            return None
