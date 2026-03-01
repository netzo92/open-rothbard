"""GitHub bounty issue source.

Searches GitHub for open issues labelled with common bounty tags.
Returns Opportunity objects sized by the dollar amount found in labels/title.

Rate limits:
  - Unauthenticated: 10 search requests/min, 60 req/hr overall
  - With GITHUB_TOKEN:  30 search requests/min, 5000 req/hr overall

Set GITHUB_TOKEN in .env for reliable operation.
"""
from __future__ import annotations

import hashlib
import logging
import re
from decimal import Decimal
from typing import Sequence

import httpx

from rothbard.config import settings
from rothbard.core.scrub import scrub
from rothbard.markets.sources.base import MarketSource, Opportunity, StrategyType

logger = logging.getLogger(__name__)

# Labels GitHub projects use to signal paid bounties
_BOUNTY_LABELS = [
    "bounty",
    "Bounty",
    "bounty-hunter",
    "funded",
    "💰",
]

# Search query — issues with any of the above labels, open, needing Python/AI skills
_SEARCH_QUERY = (
    "is:issue is:open "
    "label:bounty,Bounty,funded "
    "language:Python "
    "sort:created-desc"
)

_API_URL = "https://api.github.com/search/issues"

# Matches "$50", "$1,500", "50 USD", "50 USDC", "50$"
_MONEY_RE = re.compile(
    r"(?:\$\s*(?P<pre>[\d,]+(?:\.\d+)?)|(?P<post>[\d,]+(?:\.\d+)?)\s*(?:USD|USDC|\$))",
    re.IGNORECASE,
)

# Keywords that suggest the task is automatable by a coding agent
_CAPABLE_KEYWORDS = {
    "python", "script", "api", "bot", "scraper", "cli", "data",
    "json", "csv", "automation", "agent", "llm", "gpt", "ai",
    "bug", "fix", "test", "documentation", "research",
}

MAX_RESULTS = 20


def _parse_amount(text: str) -> Decimal | None:
    """Extract the first dollar amount from a string, or None."""
    m = _MONEY_RE.search(text)
    if not m:
        return None
    raw = (m.group("pre") or m.group("post") or "").replace(",", "")
    try:
        return Decimal(raw)
    except Exception:
        return None


def _is_automatable(title: str, body: str) -> bool:
    combined = (title + " " + body).lower()
    return any(kw in combined for kw in _CAPABLE_KEYWORDS)


class GitHubBountiesSource(MarketSource):
    """Scans GitHub for open issues with bounty labels."""

    name = "github_bounties"

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.github_token:
            h["Authorization"] = f"Bearer {settings.github_token}"
        return h

    async def scan(self) -> Sequence[Opportunity]:
        params = {
            "q": _SEARCH_QUERY,
            "per_page": MAX_RESULTS,
            "page": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(_API_URL, params=params, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("GitHub bounties fetch failed: %s", exc)
            return []

        items = data.get("items", [])
        opportunities = []

        for issue in items:
            opp = self._issue_to_opportunity(issue)
            if opp:
                opportunities.append(opp)

        logger.info("GitHub bounties: %d actionable issues found", len(opportunities))
        return opportunities

    def _issue_to_opportunity(self, issue: dict) -> Opportunity | None:
        try:
            title = scrub((issue.get("title") or "").strip(), max_length=120)
            body = scrub((issue.get("body") or "").strip(), max_length=400)
            url = issue.get("html_url", "")
            labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
            label_text = " ".join(labels)
            repo = issue.get("repository_url", "").replace(
                "https://api.github.com/repos/", ""
            )

            if not _is_automatable(title, body):
                return None

            # Try to find a dollar amount in labels first, then title, then body
            amount = (
                _parse_amount(label_text)
                or _parse_amount(title)
                or _parse_amount(body)
            )
            estimated_revenue = amount if amount and amount > 0 else Decimal("50")
            # Cap at $5000 — anything larger is likely misparse or out of scope
            estimated_revenue = min(estimated_revenue, Decimal("5000"))

            uid = hashlib.md5(url.encode()).hexdigest()[:12]

            return Opportunity(
                id=f"github:{uid}",
                strategy_type=StrategyType.FREELANCE,
                title=f"[GitHub] {title}",
                description=f"Repo: {repo}\nLabels: {label_text}\n{body[:300]}",
                expected_revenue_usdc=estimated_revenue,
                estimated_cost_usdc=Decimal("0.50"),  # worker container cost
                effort_score=5.0,
                risk_score=2.0,  # lower risk than Upwork — code-focused, no scam risk
                payload={"url": url, "platform": "github", "repo": repo},
            )
        except Exception as exc:
            logger.debug("Skipping GitHub issue: %s", exc)
            return None
