"""ArbitrageStrategy — execute cross-exchange price gap opportunities.

For SOL/USDC pairs we execute the DEX leg via Jupiter aggregator (real on-chain).
The CEX leg (Coinbase) would require the Coinbase Advanced Trade API — without it
we execute one-sided: buying SOL when it's cheap on-chain, selling when expensive.
This captures price dislocations at the cost of some execution risk.

For ETH and other non-Solana assets the strategy is logged but not yet executable
(requires CEX API keys or EVM DEX integration).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from rothbard.config import settings
from rothbard.markets.sources.base import Opportunity
from rothbard.revenue.base import ExecutionResult, RevenueStrategy
from rothbard.revenue.registry import register

logger = logging.getLogger(__name__)

# Solana token mints
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # mainnet

# Max fraction of balance to deploy per trade (conservative)
DEPLOY_FRACTION = Decimal("0.10")
MAX_DEPLOY_USDC = Decimal("25")
MAX_DEPLOY_SOL = Decimal("0.15")


@register
class ArbitrageStrategy(RevenueStrategy):
    name = "arbitrage"
    min_capital = Decimal("5")  # $5 USDC minimum

    async def execute(self, opportunity: Opportunity, wallet) -> ExecutionResult:
        payload = opportunity.payload
        gap_pct = payload.get("gap_pct", 0)
        buy_on = payload.get("buy_on", "unknown")
        base_asset = payload.get("base", "ETH")
        quote_asset = payload.get("quote", "USDC")

        if base_asset == "SOL":
            return await self._execute_solana(opportunity, gap_pct, buy_on)

        # ── Non-Solana pairs: CEX API needed for full execution ────────────────
        logger.info(
            "Arbitrage detected for %s/%s (%.2f%% gap) — CEX leg requires "
            "Coinbase Advanced Trade API. Logging opportunity only.",
            base_asset, quote_asset, gap_pct,
        )
        return ExecutionResult(
            success=False,
            details=(
                f"{base_asset}/{quote_asset} arb detected ({gap_pct:.2f}% gap) "
                f"but CEX execution not yet implemented. "
                f"Add COINBASE_ADVANCED_API_KEY to enable."
            ),
        )

    async def _execute_solana(
        self, opportunity: Opportunity, gap_pct: float, buy_on: str
    ) -> ExecutionResult:
        """Execute the Solana DEX leg via Jupiter aggregator."""
        from rothbard.core import nodes

        sol_wallet = nodes._sol_wallet
        if not sol_wallet or not sol_wallet.is_connected:
            return ExecutionResult(
                success=False,
                details="Solana wallet not connected — cannot execute DEX leg",
            )

        usdc_bal = await sol_wallet.get_usdc_balance()
        sol_bal = await sol_wallet.get_sol_balance()

        try:
            if buy_on == "dex":
                # SOL is cheaper on-chain → buy SOL with USDC via Jupiter
                deploy = min(usdc_bal * DEPLOY_FRACTION, MAX_DEPLOY_USDC)
                if deploy < self.min_capital:
                    return ExecutionResult(
                        success=False,
                        details=f"Insufficient USDC on Solana: {usdc_bal:.2f} (need {self.min_capital})",
                    )
                amount_micro = int(deploy * Decimal("1_000_000"))
                out_lamports, sig = await sol_wallet.jupiter_swap(
                    input_mint=USDC_MINT,
                    output_mint=SOL_MINT,
                    amount=amount_micro,
                )
                out_sol = Decimal(out_lamports) / Decimal("1_000_000_000")
                net = deploy * Decimal(str(gap_pct / 100))
                return ExecutionResult(
                    success=True,
                    profit_usdc=net.quantize(Decimal("0.0001")),
                    details=(
                        f"Jupiter swap: ${deploy:.2f} USDC → {out_sol:.5f} SOL "
                        f"({gap_pct:.2f}% gap vs Coinbase) | sig: {sig[:20]}…"
                    ),
                )
            else:
                # SOL is more expensive on-chain → sell SOL for USDC via Jupiter
                deploy = min(sol_bal * DEPLOY_FRACTION, MAX_DEPLOY_SOL)
                if deploy < Decimal("0.01"):
                    return ExecutionResult(
                        success=False,
                        details=f"Insufficient SOL on Solana: {sol_bal:.4f}",
                    )
                amount_lam = int(deploy * Decimal("1_000_000_000"))
                out_micro, sig = await sol_wallet.jupiter_swap(
                    input_mint=SOL_MINT,
                    output_mint=USDC_MINT,
                    amount=amount_lam,
                )
                out_usdc = Decimal(out_micro) / Decimal("1_000_000")
                net = out_usdc * Decimal(str(gap_pct / 100))
                return ExecutionResult(
                    success=True,
                    profit_usdc=net.quantize(Decimal("0.0001")),
                    details=(
                        f"Jupiter swap: {deploy:.5f} SOL → ${out_usdc:.2f} USDC "
                        f"({gap_pct:.2f}% gap vs Coinbase) | sig: {sig[:20]}…"
                    ),
                )
        except Exception as exc:
            logger.error("Jupiter swap failed: %s", exc)
            return ExecutionResult(success=False, details=f"Jupiter swap error: {exc}")
