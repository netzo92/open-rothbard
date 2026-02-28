"""Tests for the market scanner and scorer."""
from __future__ import annotations

from decimal import Decimal

import pytest

from rothbard.markets.scorer import filter_by_capital, rank, score
from rothbard.markets.sources.base import Opportunity, StrategyType


def make_opp(
    id: str = "test:1",
    strategy_type: StrategyType = StrategyType.TRADE,
    expected_revenue: Decimal = Decimal("10"),
    estimated_cost: Decimal = Decimal("1"),
    effort: float = 5.0,
    risk: float = 5.0,
) -> Opportunity:
    return Opportunity(
        id=id,
        strategy_type=strategy_type,
        title="Test opportunity",
        description="Test",
        expected_revenue_usdc=expected_revenue,
        estimated_cost_usdc=estimated_cost,
        effort_score=effort,
        risk_score=risk,
    )


def test_opportunity_roi():
    opp = make_opp(expected_revenue=Decimal("10"), estimated_cost=Decimal("2"))
    assert opp.expected_roi == Decimal("8")


def test_opportunity_roi_pct():
    opp = make_opp(expected_revenue=Decimal("10"), estimated_cost=Decimal("2"))
    assert abs(opp.roi_pct - 400.0) < 0.01


def test_score_higher_roi_wins():
    low = make_opp(id="low", expected_revenue=Decimal("5"), estimated_cost=Decimal("1"))
    high = make_opp(id="high", expected_revenue=Decimal("20"), estimated_cost=Decimal("1"))
    assert score(high) > score(low)


def test_score_lower_risk_wins():
    risky = make_opp(id="risky", expected_revenue=Decimal("10"), estimated_cost=Decimal("1"), risk=9.0)
    safe = make_opp(id="safe", expected_revenue=Decimal("10"), estimated_cost=Decimal("1"), risk=2.0)
    assert score(safe) > score(risky)


def test_score_negative_roi():
    opp = make_opp(expected_revenue=Decimal("0"), estimated_cost=Decimal("5"))
    assert score(opp) < 0


def test_rank_orders_best_first():
    opps = [
        make_opp("c", expected_revenue=Decimal("5")),
        make_opp("a", expected_revenue=Decimal("20")),
        make_opp("b", expected_revenue=Decimal("10")),
    ]
    ranked = rank(opps)
    assert ranked[0].id == "a"
    assert ranked[1].id == "b"
    assert ranked[2].id == "c"


def test_filter_by_capital_removes_too_expensive():
    opps = [
        make_opp("cheap", estimated_cost=Decimal("1")),
        make_opp("expensive", estimated_cost=Decimal("1000")),
    ]
    filtered = filter_by_capital(opps, available_usdc=Decimal("50"))
    assert len(filtered) == 1
    assert filtered[0].id == "cheap"
