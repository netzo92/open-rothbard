"""Resource budget tracker — ensures infra spend stays within treasury limits."""
from __future__ import annotations

import logging
from decimal import Decimal

from rothbard.config import settings

logger = logging.getLogger(__name__)


class ResourceBudget:
    """Tracks infra spend per cycle and enforces the max_infra_spend_pct limit."""

    def __init__(self) -> None:
        self._cycle_spend: Decimal = Decimal("0")

    def reset(self) -> None:
        """Call at the start of each cycle."""
        self._cycle_spend = Decimal("0")

    def can_spend(self, amount: Decimal, treasury_balance: Decimal) -> bool:
        """Return True if spending `amount` stays within the cycle budget."""
        max_budget = settings.max_infra_spend_pct * float(treasury_balance)
        projected = float(self._cycle_spend) + float(amount)
        return projected <= max_budget

    def record_spend(self, amount: Decimal) -> None:
        self._cycle_spend += amount
        logger.debug("Infra spend this cycle: %s USDC", self._cycle_spend)

    @property
    def cycle_spend(self) -> Decimal:
        return self._cycle_spend
