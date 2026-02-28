"""Base class for all market opportunity sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Sequence


class StrategyType(StrEnum):
    TRADE = "trade"
    FREELANCE = "freelance"
    ARBITRAGE = "arbitrage"
    CONTENT = "content"


@dataclass
class Opportunity:
    """A discovered market opportunity."""

    id: str
    strategy_type: StrategyType
    title: str
    description: str
    # Expected gross revenue in USDC
    expected_revenue_usdc: Decimal = Decimal("0")
    # Estimated cost (gas, infra, fees) in USDC
    estimated_cost_usdc: Decimal = Decimal("0")
    # Rough effort score 1-10 (1=easy/fast)
    effort_score: float = 5.0
    # Risk score 1-10 (1=very safe)
    risk_score: float = 5.0
    # Source-specific payload (passed through to the strategy executor)
    payload: dict = field(default_factory=dict)

    @property
    def expected_roi(self) -> Decimal:
        if self.estimated_cost_usdc == 0:
            return self.expected_revenue_usdc
        return self.expected_revenue_usdc - self.estimated_cost_usdc

    @property
    def roi_pct(self) -> float:
        if self.estimated_cost_usdc == 0:
            return float("inf")
        return float(self.expected_roi / self.estimated_cost_usdc * 100)


class MarketSource(ABC):
    """ABC for all opportunity scanners.

    Each implementation polls one data source (DeFiLlama, freelance RSS,
    exchange APIs, etc.) and returns a list of Opportunity objects.
    """

    name: str = "base"

    @abstractmethod
    async def scan(self) -> Sequence[Opportunity]:
        """Return all currently available opportunities from this source."""
        ...

    async def is_available(self) -> bool:
        """Return False if the source is down / rate-limited / misconfigured."""
        return True
