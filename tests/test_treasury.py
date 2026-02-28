"""Tests for the Treasury P&L ledger."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from rothbard.finance.treasury import LedgerCategory, Treasury


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    """Point episodic DB at a temp path for tests."""
    from rothbard import config
    from rothbard.memory import episodic

    config.settings.sqlite_path = tmp_path / "test.db"
    await episodic.init_db()


async def test_record_income_and_pnl():
    treasury = Treasury()
    await treasury.record_income(LedgerCategory.INCOME_TRADE, Decimal("5.00"), "test trade")
    pnl = await treasury.get_pnl()
    assert pnl == Decimal("5.00")


async def test_record_expense_reduces_pnl():
    treasury = Treasury()
    await treasury.record_income(LedgerCategory.INCOME_TRADE, Decimal("10.00"))
    await treasury.record_expense(LedgerCategory.EXPENSE_GAS, Decimal("1.50"))
    pnl = await treasury.get_pnl()
    assert pnl == Decimal("8.50")


async def test_reinvest_amount():
    treasury = Treasury()
    profit = Decimal("100")
    reinvest = treasury.reinvest_amount(profit)
    reserve = treasury.reserve_amount(profit)
    assert reinvest + reserve == profit


async def test_max_infra_budget():
    treasury = Treasury()
    balance = Decimal("1000")
    budget = treasury.max_infra_budget(balance)
    from rothbard.config import settings
    expected = balance * Decimal(str(settings.max_infra_spend_pct))
    assert abs(budget - expected) < Decimal("0.01")
