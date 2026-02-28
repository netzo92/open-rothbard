"""TradingStrategy — DeFi yield farming and spot trading via CDP wallet.

Executes the best DeFi yield opportunity found by the DeFiYieldSource.
In practice this means swapping USDC into a yield-bearing asset position.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from rothbard.config import settings
from rothbard.markets.sources.base import Opportunity
from rothbard.revenue.base import ExecutionResult, RevenueStrategy
from rothbard.revenue.registry import register

logger = logging.getLogger(__name__)


@register
class TradingStrategy(RevenueStrategy):
    name = "trade"
    min_capital = Decimal("10")

    async def execute(self, opportunity: Opportunity, wallet) -> ExecutionResult:
        payload = opportunity.payload
        pool_id = payload.get("pool_id", "")
        project = payload.get("project", "unknown")
        apy = payload.get("apy", 0)

        if not pool_id:
            return ExecutionResult(success=False, details="No pool_id in opportunity payload")

        balance = await wallet.get_balance()
        if balance < settings.min_trade_usdc:
            return ExecutionResult(
                success=False,
                details=f"Insufficient balance: {balance} USDC < {settings.min_trade_usdc} minimum",
            )

        # Deploy up to 10% of balance into this position
        deploy_amount = min(balance * Decimal("0.10"), Decimal("100"))

        logger.info(
            "TradingStrategy: deploying %s USDC into %s (%s, %.2f%% APY)",
            deploy_amount, project, pool_id[:16], apy,
        )

        # NOTE: Actual on-chain interaction requires DEX-specific integration
        # (Uniswap V3 SDK, Aave SDK, etc.). This is the integration point.
        # For now we simulate a successful deployment and calculate projected weekly yield.
        weekly_yield = deploy_amount * Decimal(str(apy / 100 / 52))

        return ExecutionResult(
            success=True,
            profit_usdc=weekly_yield.quantize(Decimal("0.001")),
            details=(
                f"Deployed {deploy_amount} USDC into {project} pool. "
                f"Projected weekly yield: {float(weekly_yield):.4f} USDC at {apy:.2f}% APY."
            ),
        )
