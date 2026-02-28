"""Content & affiliate opportunity source.

Finds trending topics and affiliate programs the agent can generate
content for. Uses Google Trends (via pytrends-compatible scrape) and
Amazon Associates public data.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

# Google Trends daily trending topics (JSON endpoint, no auth)
TRENDS_URL = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"

# Simple affiliate niche list — agent can generate content targeting these
AFFILIATE_NICHES = [
    {"niche": "crypto wallets", "avg_commission_usd": 15.0, "competition": "medium"},
    {"niche": "VPN services", "avg_commission_usd": 40.0, "competition": "high"},
    {"niche": "web hosting", "avg_commission_usd": 65.0, "competition": "high"},
    {"niche": "AI writing tools", "avg_commission_usd": 20.0, "competition": "medium"},
    {"niche": "online courses", "avg_commission_usd": 30.0, "competition": "low"},
    {"niche": "password managers", "avg_commission_usd": 25.0, "competition": "low"},
]

CONTENT_COST_PER_ARTICLE = Decimal("0.10")  # Claude API cost for ~1000 word article


class ContentSource(MarketSource):
    """Finds content + affiliate opportunities from trending topics."""

    name = "content"

    async def scan(self) -> Sequence[Opportunity]:
        opportunities = []

        # Affiliate niches (always available)
        for niche in AFFILIATE_NICHES:
            opp = self._niche_to_opportunity(niche)
            opportunities.append(opp)

        # Trending topics overlay
        trending = await self._fetch_trending()
        for topic in trending[:5]:
            opp = self._trending_to_opportunity(topic)
            if opp:
                opportunities.append(opp)

        logger.info("Content scanner found %d opportunities", len(opportunities))
        return opportunities

    def _niche_to_opportunity(self, niche: dict) -> Opportunity:
        uid = hashlib.md5(niche["niche"].encode()).hexdigest()[:12]
        commission = Decimal(str(niche["avg_commission_usd"]))
        competition_penalty = {"low": 1.0, "medium": 0.6, "high": 0.3}.get(
            niche["competition"], 0.5
        )
        # Pessimistic: 1 conversion per 10 articles published
        expected_revenue = commission * Decimal(str(competition_penalty)) * Decimal("0.1")

        return Opportunity(
            id=f"content:affiliate:{uid}",
            strategy_type=StrategyType.CONTENT,
            title=f"Affiliate content: {niche['niche']}",
            description=(
                f"Generate SEO-optimized review article targeting '{niche['niche']}' affiliate. "
                f"Avg commission ${niche['avg_commission_usd']}, "
                f"competition: {niche['competition']}."
            ),
            expected_revenue_usdc=expected_revenue.quantize(Decimal("0.01")),
            estimated_cost_usdc=CONTENT_COST_PER_ARTICLE,
            effort_score=4.0,
            risk_score=7.0,  # content takes time to rank, uncertain revenue
            payload={
                "type": "affiliate",
                "niche": niche["niche"],
                "avg_commission_usd": niche["avg_commission_usd"],
                "competition": niche["competition"],
            },
        )

    def _trending_to_opportunity(self, topic: str) -> Opportunity | None:
        if not topic:
            return None
        uid = hashlib.md5(topic.encode()).hexdigest()[:12]
        return Opportunity(
            id=f"content:trending:{uid}",
            strategy_type=StrategyType.CONTENT,
            title=f"Trending content: {topic}",
            description=(
                f"Generate and publish an article on trending topic: '{topic}'. "
                "Monetize via display ads or affiliate links."
            ),
            expected_revenue_usdc=Decimal("0.50"),
            estimated_cost_usdc=CONTENT_COST_PER_ARTICLE,
            effort_score=3.0,
            risk_score=6.0,
            payload={"type": "trending", "topic": topic},
        )

    async def _fetch_trending(self) -> list[str]:
        try:
            import xml.etree.ElementTree as ET

            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(TRENDS_URL)
                resp.raise_for_status()

            root = ET.fromstring(resp.text)
            titles = [
                (item.findtext("title") or "").strip()
                for item in root.findall(".//item")
            ]
            return [t for t in titles if t][:10]
        except Exception as exc:
            logger.debug("Google Trends fetch failed: %s", exc)
            return []
