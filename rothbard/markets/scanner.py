"""OpportunityScanner — aggregates all market sources."""
from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from rothbard.config import settings
from rothbard.markets.scorer import filter_by_capital, rank
from rothbard.markets.sources.arbitrage import ArbitrageSource
from rothbard.markets.sources.base import Opportunity
from rothbard.markets.sources.content import ContentSource
from rothbard.markets.sources.defi import DeFiYieldSource
from rothbard.markets.sources.freelance import UpworkSource
from rothbard.markets.sources.github_bounties import GitHubBountiesSource
from rothbard.markets.sources.solana_defi import SolanaDeFiSource

logger = logging.getLogger(__name__)


class OpportunityScanner:
    """Polls all market sources concurrently and returns ranked opportunities."""

    def __init__(self) -> None:
        self.sources = [
            DeFiYieldSource(),
            SolanaDeFiSource(),
            UpworkSource(),
            GitHubBountiesSource(),
            ArbitrageSource(),
            ContentSource(),
        ]

    async def scan_all(self, available_usdc=None) -> list[Opportunity]:
        """Run all sources concurrently, rank results."""
        results = await asyncio.gather(
            *[self._safe_scan(src) for src in self.sources],
            return_exceptions=False,
        )
        all_opps: list[Opportunity] = []
        for batch in results:
            all_opps.extend(batch)

        if available_usdc is not None:
            all_opps = filter_by_capital(all_opps, available_usdc)

        focus = settings.focused_strategy_types
        if focus:
            all_opps = [o for o in all_opps if str(o.strategy_type) in focus]
            logger.info("Strategy focus active: %s", focus)

        ranked = rank(all_opps)
        logger.info("Scanner found %d total opportunities, ranked", len(ranked))
        return ranked

    async def _safe_scan(self, source) -> list[Opportunity]:
        try:
            return list(await source.scan())
        except Exception as exc:
            logger.error("Source %s failed: %s", source.name, exc)
            return []
