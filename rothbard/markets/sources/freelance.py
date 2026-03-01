"""Freelance microtask opportunity source.

Scrapes public RSS feeds and APIs from freelance platforms to find tasks
the agent (or its workers) can autonomously complete.

Currently supports:
  - Upwork RSS (public job feed, no auth required)
  - Mechanical Turk HITs via public MTurk API (read-only)
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.core.scrub import scrub
from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

UPWORK_RSS_URL = "https://www.upwork.com/ab/feed/jobs/rss?q=python+ai+agent&sort=recency"
MTurk_PUBLIC_URL = "https://www.mturk.com/mturk/findhits?description=&keywords=data+entry+simple&Search=Search"

# Keywords the agent is capable of completing autonomously
CAPABLE_KEYWORDS = {
    "data entry", "web scraping", "python", "api", "json", "csv",
    "research", "writing", "content", "seo", "summarize", "transcribe",
    "classify", "label", "categorize", "translate",
}

MAX_RESULTS = 15


class UpworkSource(MarketSource):
    """Scans Upwork RSS for automatable freelance tasks."""

    name = "upwork"

    async def scan(self) -> Sequence[Opportunity]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(UPWORK_RSS_URL, headers=headers)
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("Upwork RSS fetch failed: %s", exc)
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as exc:
            logger.warning("Upwork RSS parse error: %s", exc)
            return []

        items = root.findall(".//item")
        opportunities = []

        for item in items[:MAX_RESULTS]:
            opp = self._item_to_opportunity(item)
            if opp:
                opportunities.append(opp)

        logger.info("Upwork scanner found %d actionable tasks", len(opportunities))
        return opportunities

    def _item_to_opportunity(self, item: ET.Element) -> Opportunity | None:
        try:
            title = scrub((item.findtext("title") or "").strip(), max_length=120)
            desc  = scrub((item.findtext("description") or "").strip(), max_length=400)
            link = (item.findtext("link") or "").strip()
            combined = (title + " " + desc).lower()

            # Only pursue tasks the agent can handle autonomously
            if not any(kw in combined for kw in CAPABLE_KEYWORDS):
                return None

            # Try to parse budget from description (e.g. "$50.00 – $100.00")
            budget_match = re.search(r"\$(\d+(?:\.\d+)?)", desc)
            estimated_revenue = Decimal(budget_match.group(1)) if budget_match else Decimal("25")

            uid = hashlib.md5(link.encode()).hexdigest()[:12]

            return Opportunity(
                id=f"upwork:{uid}",
                strategy_type=StrategyType.FREELANCE,
                title=title,
                description=desc,
                expected_revenue_usdc=estimated_revenue,
                estimated_cost_usdc=Decimal("0.50"),  # worker container cost
                effort_score=6.0,
                risk_score=3.0,
                payload={"url": link, "platform": "upwork"},
            )
        except Exception as exc:
            logger.debug("Skipping Upwork item: %s", exc)
            return None
