"""Treasury — P&L ledger and profit routing rules.

All income and expenses flow through here. The ledger is persisted to SQLite
so the agent has a full financial history across restarts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rothbard.config import settings
from rothbard.memory.episodic import LedgerEntry, async_session

logger = logging.getLogger(__name__)


class LedgerCategory(StrEnum):
    INCOME_TRADE = "income:trade"
    INCOME_FREELANCE = "income:freelance"
    INCOME_ARBITRAGE = "income:arbitrage"
    INCOME_CONTENT = "income:content"
    INCOME_X402 = "income:x402"
    EXPENSE_INFRA = "expense:infra"
    EXPENSE_GAS = "expense:gas"
    EXPENSE_TRADE = "expense:trade"


class Treasury:
    """Tracks all financial flows and applies routing rules."""

    async def record_income(
        self,
        category: LedgerCategory,
        amount: Decimal,
        details: str = "",
        strategy: str = "",
    ) -> None:
        async with async_session() as session:
            entry = LedgerEntry(
                ts=datetime.now(timezone.utc),
                category=str(category),
                amount_usdc=str(amount),
                direction="credit",
                strategy=strategy,
                details=details,
            )
            session.add(entry)
            await session.commit()
        logger.info("[Treasury] +%s USDC (%s) %s", amount, category, details)

    async def record_expense(
        self,
        category: LedgerCategory,
        amount: Decimal,
        details: str = "",
        strategy: str = "",
    ) -> None:
        async with async_session() as session:
            entry = LedgerEntry(
                ts=datetime.now(timezone.utc),
                category=str(category),
                amount_usdc=str(amount),
                direction="debit",
                strategy=strategy,
                details=details,
            )
            session.add(entry)
            await session.commit()
        logger.info("[Treasury] -%s USDC (%s) %s", amount, category, details)

    async def get_pnl(self, since: datetime | None = None) -> Decimal:
        """Net P&L = sum(credits) - sum(debits) since given datetime."""
        async with async_session() as session:
            entries = await self._fetch_entries(session, since)
        pnl = Decimal("0")
        for e in entries:
            amt = Decimal(e.amount_usdc)
            pnl += amt if e.direction == "credit" else -amt
        return pnl

    async def get_total_income(self, since: datetime | None = None) -> Decimal:
        async with async_session() as session:
            entries = await self._fetch_entries(session, since, direction="credit")
        return sum((Decimal(e.amount_usdc) for e in entries), Decimal("0"))

    async def get_total_expenses(self, since: datetime | None = None) -> Decimal:
        async with async_session() as session:
            entries = await self._fetch_entries(session, since, direction="debit")
        return sum((Decimal(e.amount_usdc) for e in entries), Decimal("0"))

    async def _fetch_entries(
        self,
        session: AsyncSession,
        since: datetime | None,
        direction: str | None = None,
    ) -> Sequence[LedgerEntry]:
        q = select(LedgerEntry)
        if since:
            q = q.where(LedgerEntry.ts >= since)
        if direction:
            q = q.where(LedgerEntry.direction == direction)
        result = await session.execute(q)
        return result.scalars().all()

    # ── routing rules ─────────────────────────────────────────────────────────

    def reinvest_amount(self, profit: Decimal) -> Decimal:
        """Amount of profit that should be reinvested per settings."""
        return (profit * Decimal(str(settings.profit_reinvest_pct))).quantize(Decimal("0.01"))

    def reserve_amount(self, profit: Decimal) -> Decimal:
        return profit - self.reinvest_amount(profit)

    def max_infra_budget(self, treasury_balance: Decimal) -> Decimal:
        """Max USDC the agent may spend on infra in one cycle."""
        return (treasury_balance * Decimal(str(settings.max_infra_spend_pct))).quantize(Decimal("0.01"))
