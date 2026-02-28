"""Opportunity scorer — ranks opportunities by risk-adjusted ROI.

Score = (expected_roi / effort_score) / risk_score

Higher score = better opportunity to pursue first.
"""
from __future__ import annotations

from decimal import Decimal

from rothbard.markets.sources.base import Opportunity


def score(opp: Opportunity) -> float:
    """Return a priority score. Higher = pursue first."""
    roi = float(opp.expected_roi)
    if roi <= 0:
        return -999.0
    effort = max(opp.effort_score, 0.1)
    risk = max(opp.risk_score, 0.1)
    return roi / effort / risk


def rank(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Return opportunities sorted best-first."""
    return sorted(opportunities, key=score, reverse=True)


def filter_by_capital(
    opportunities: list[Opportunity],
    available_usdc: Decimal,
) -> list[Opportunity]:
    """Remove opportunities whose cost exceeds available capital."""
    return [o for o in opportunities if o.estimated_cost_usdc <= available_usdc]
