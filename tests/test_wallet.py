"""Tests for the Wallet — runs in stub mode (no real CDP credentials needed)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from rothbard.finance.wallet import Wallet


async def test_wallet_stub_address():
    """Without CDP configured, wallet should return zero address."""
    wallet = Wallet()
    await wallet.connect()  # Will log warning and skip CDP in test env
    assert wallet.address.startswith("0x")


async def test_wallet_stub_balance():
    wallet = Wallet()
    await wallet.connect()
    balance = await wallet.get_balance()
    assert balance == Decimal("0")


async def test_wallet_faucet_only_on_testnet():
    from rothbard.config import settings

    wallet = Wallet()
    await wallet.connect()

    # Force mainnet setting
    original = settings.network_id
    settings.network_id = "base-mainnet"
    with pytest.raises(RuntimeError, match="testnet"):
        await wallet.fund_from_faucet()
    settings.network_id = original
