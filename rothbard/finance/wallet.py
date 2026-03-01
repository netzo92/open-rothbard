"""CDP-backed wallet management.

Wraps the Coinbase Developer Platform SDK to give the agent a persistent,
self-custodied wallet on Base. On first run a wallet is created and the
encrypted seed is saved to disk. Subsequent runs reload from disk.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from rothbard.config import settings
from rothbard.core.audit import AuditAction, AuditDenied, require_approval

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_EVM_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class Wallet:
    """Thin wrapper around the CDP SDK wallet."""

    def __init__(self) -> None:
        self._wallet = None  # cdp.Wallet instance, populated by connect()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Load or create the agent wallet."""
        try:
            import cdp  # type: ignore[import]
        except ImportError:
            logger.warning("cdp-sdk not installed — wallet running in stub mode")
            return

        if not self._configure_cdp(cdp):
            return
        if not hasattr(cdp, "Wallet"):
            logger.warning(
                "Unsupported cdp module (%s): missing Wallet type; wallet running in stub mode",
                getattr(cdp, "__file__", "unknown module"),
            )
            return

        wallet_path = settings.wallet_path
        if wallet_path.exists():
            logger.info("Loading existing wallet from %s", wallet_path)
            self._wallet = self._load(wallet_path)
        else:
            logger.info("Creating new wallet on %s", settings.network_id)
            self._wallet = cdp.Wallet.create(network_id=settings.network_id)
            self._save(wallet_path)
            logger.info("Wallet created: %s", self.address)

    def _configure_cdp(self, cdp_module) -> bool:
        """Support multiple cdp-sdk API surfaces without crashing startup."""
        key_name = settings.cdp_api_key_name
        private_key = settings.cdp_api_key_private_key
        try:
            if hasattr(cdp_module, "Cdp") and hasattr(cdp_module.Cdp, "configure"):
                cdp_module.Cdp.configure(
                    api_key_name=key_name,
                    private_key=private_key,
                )
                return True
            if hasattr(cdp_module, "configure"):
                cdp_module.configure(
                    api_key_name=key_name,
                    private_key=private_key,
                )
                return True

            logger.warning(
                "Unsupported cdp module (%s): no configure API; wallet running in stub mode",
                getattr(cdp_module, "__file__", "unknown module"),
            )
            return False
        except Exception as exc:
            logger.error("Failed to configure CDP SDK: %s", exc)
            return False

    def _save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        exported = self._wallet.export_data()
        if hasattr(exported, "model_dump"):
            exported = exported.model_dump()
        elif hasattr(exported, "dict"):
            exported = exported.dict()
        path.write_text(json.dumps(exported))
        path.chmod(0o600)

    def _load(self, path: Path):
        import cdp  # type: ignore[import]
        data = json.loads(path.read_text())
        if hasattr(cdp, "WalletData"):
            return cdp.Wallet.import_data(cdp.WalletData(**data))
        return cdp.Wallet.import_data(data)

    # ── queries ───────────────────────────────────────────────────────────────

    @property
    def address(self) -> str:
        if self._wallet is None:
            return "0x0000000000000000000000000000000000000000"
        return self._wallet.default_address.address_id

    async def get_balance(self, asset_id: str = "usdc") -> Decimal:
        if self._wallet is None:
            return Decimal("0")
        try:
            balance = self._wallet.balance(asset_id)
            return Decimal(str(balance))
        except Exception as exc:
            logger.error("Failed to fetch balance: %s", exc)
            return Decimal("0")

    async def get_eth_balance(self) -> Decimal:
        return await self.get_balance("eth")

    # ── mutations ─────────────────────────────────────────────────────────────

    async def send(
        self,
        to: str,
        amount: Decimal,
        asset_id: str = "usdc",
    ) -> str:
        """Transfer assets. Returns transaction hash."""
        if self._wallet is None:
            raise RuntimeError("Wallet not connected")

        if not _EVM_ADDR_RE.match(to):
            raise ValueError(f"Invalid EVM destination address: {to!r}")

        cap = settings.max_single_transfer_usdc
        if amount > cap:
            raise ValueError(f"Transfer amount {amount} exceeds single-transaction cap {cap}")

        await require_approval(AuditAction(
            action_type="transaction",
            title=f"Send {amount} {asset_id.upper()} on Base",
            details={
                "from": self.address,
                "to": to,
                "amount": str(amount),
                "asset": asset_id.upper(),
                "network": settings.network_id,
            },
            risk="high",
        ))

        transfer = self._wallet.transfer(float(amount), asset_id, to)
        transfer.wait()
        logger.info("Sent %s %s to %s | tx: %s", amount, asset_id, to, transfer.transaction_hash)
        return transfer.transaction_hash

    async def fund_from_faucet(self) -> None:
        """Request testnet funds (base-sepolia only)."""
        if not settings.is_testnet:
            raise RuntimeError("Faucet only available on testnet")
        if self._wallet is None:
            raise RuntimeError("Wallet not connected")
        faucet_tx = self._wallet.faucet()
        logger.info("Faucet tx: %s", faucet_tx.transaction_hash)
