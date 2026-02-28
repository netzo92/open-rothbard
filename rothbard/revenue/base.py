"""Base class for all revenue strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rothbard.finance.wallet import Wallet
    from rothbard.markets.sources.base import Opportunity


@dataclass
class ExecutionResult:
    success: bool
    profit_usdc: Decimal = Decimal("0")
    details: str = ""


class RevenueStrategy(ABC):
    """All revenue strategies implement this interface.

    Strategies self-register via the @register decorator in registry.py.
    """

    name: str = "base"
    # Minimum USDC required in treasury to run this strategy
    min_capital: Decimal = Decimal("1")

    @abstractmethod
    async def execute(
        self,
        opportunity: "Opportunity",
        wallet: "Wallet",
    ) -> ExecutionResult:
        """Execute the opportunity. Must be idempotent when possible."""
        ...

    def can_run(self, treasury_balance: Decimal) -> bool:
        return treasury_balance >= self.min_capital
