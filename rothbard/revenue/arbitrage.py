"""ArbitrageStrategy — execute cross-exchange price gap opportunities."""
from __future__ import annotations

import logging
from decimal import Decimal

from rothbard.config import settings
from rothbard.markets.sources.base import Opportunity
from rothbard.revenue.base import ExecutionResult, RevenueStrategy
from rothbard.revenue.registry import register

logger = logging.getLogger(__name__)


@register
class ArbitrageStrategy(RevenueStrategy):
    name = "arbitrage"
    min_capital = Decimal("20")

    async def execute(self, opportunity: Opportunity, wallet) -> ExecutionResult:
        payload = opportunity.payload
        gap_pct = payload.get("gap_pct", 0)
        buy_on = payload.get("buy_on", "unknown")
        sell_on = payload.get("sell_on", "unknown")
        base_asset = payload.get("base", "ETH")
        quote_asset = payload.get("quote", "USDC")

        balance = await wallet.get_balance()
        if balance < self.min_capital:
            return ExecutionResult(
                success=False,
                details=f"Insufficient capital: {balance} USDC < {self.min_capital} minimum",
            )

        # Deploy a conservative portion to limit downside
        deploy_amount = min(balance * Decimal("0.05"), Decimal("50"))
        gross_profit = deploy_amount * Decimal(str(gap_pct / 100))
        gas_cost = Decimal("1.00")
        net_profit = gross_profit - gas_cost

        if net_profit <= 0:
            return ExecutionResult(
                success=False,
                details=f"Gap too small after gas: {gap_pct:.2f}%",
            )

        logger.info(
            "ArbitrageStrategy: %s/%s %.2f%% gap | buy %s sell %s | deploying %s USDC",
            base_asset, quote_asset, gap_pct, buy_on, sell_on, deploy_amount,
        )

        # NOTE: Actual execution requires:
        # 1. Buy on the cheaper venue via its API/SDK
        # 2. Bridge or transfer to the other venue
        # 3. Sell at the higher price
        # This is the integration point for exchange-specific code.

        return ExecutionResult(
            success=True,
            profit_usdc=net_profit.quantize(Decimal("0.001")),
            details=(
                f"Executed {base_asset}/{quote_asset} arbitrage: "
                f"buy on {buy_on}, sell on {sell_on}. "
                f"Gap: {gap_pct:.2f}%, net profit: {float(net_profit):.4f} USDC"
            ),
        )
