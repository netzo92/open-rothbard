"""Solana self-custodied wallet.

Uses `solders` for keypair generation and `solana` for RPC calls.
Keypair is generated once and persisted as a JSON byte-array at
~/.rothbard/solana_keypair.json (standard Solana CLI format).

Supports:
  - SOL balance queries
  - USDC SPL token balance queries
  - SOL and USDC transfers
  - Devnet airdrop (development only)
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from pathlib import Path

from rothbard.config import settings
from rothbard.core.audit import AuditAction, require_approval

logger = logging.getLogger(__name__)

# Base58 alphabet excludes 0, O, I, l to avoid visual confusion
_SOL_ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# USDC mint addresses
USDC_MINT_MAINNET = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_MINT_DEVNET = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

LAMPORTS_PER_SOL = 1_000_000_000
USDC_DECIMALS = 6


def _usdc_mint() -> str:
    return USDC_MINT_DEVNET if "devnet" in settings.solana_rpc_url else USDC_MINT_MAINNET


class SolanaWallet:
    """Self-custodied Solana wallet backed by a local keypair file."""

    def __init__(self) -> None:
        self._keypair = None   # solders.Keypair
        self._client = None    # solana.rpc.async_api.AsyncClient

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Load or generate the Solana keypair and open RPC connection."""
        try:
            from solders.keypair import Keypair  # type: ignore[import]
            from solana.rpc.async_api import AsyncClient  # type: ignore[import]
        except ImportError:
            logger.warning("solders/solana not installed — Solana wallet in stub mode")
            return

        keypair_path = settings.solana_keypair_path
        if keypair_path.exists():
            logger.info("Loading Solana keypair from %s", keypair_path)
            self._keypair = self._load_keypair(keypair_path)
        else:
            logger.info("Generating new Solana keypair")
            self._keypair = Keypair()
            self._save_keypair(keypair_path)

        self._client = AsyncClient(settings.solana_rpc_url)
        logger.info("Solana wallet: %s (%s)", self.address, settings.solana_rpc_url)

    def _save_keypair(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Standard Solana CLI format: JSON array of 64 bytes
        path.write_text(json.dumps(list(bytes(self._keypair))))
        path.chmod(0o600)

    def _load_keypair(self, path: Path):
        from solders.keypair import Keypair  # type: ignore[import]
        raw = json.loads(path.read_text())
        return Keypair.from_bytes(bytes(raw))

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def address(self) -> str:
        if self._keypair is None:
            return "11111111111111111111111111111111"
        return str(self._keypair.pubkey())

    @property
    def is_connected(self) -> bool:
        return self._keypair is not None and self._client is not None

    # ── queries ───────────────────────────────────────────────────────────────

    async def get_sol_balance(self) -> Decimal:
        """Return SOL balance in SOL (not lamports)."""
        if not self.is_connected:
            return Decimal("0")
        try:
            from solders.pubkey import Pubkey  # type: ignore[import]
            resp = await self._client.get_balance(Pubkey.from_string(self.address))
            lamports = resp.value
            return Decimal(lamports) / Decimal(LAMPORTS_PER_SOL)
        except Exception as exc:
            logger.error("Solana SOL balance failed: %s", exc)
            return Decimal("0")

    async def get_usdc_balance(self) -> Decimal:
        """Return USDC balance (SPL token)."""
        if not self.is_connected:
            return Decimal("0")
        try:
            from solders.pubkey import Pubkey  # type: ignore[import]
            from spl.token.async_client import AsyncToken  # type: ignore[import]
            from spl.token.constants import TOKEN_PROGRAM_ID  # type: ignore[import]

            mint = Pubkey.from_string(_usdc_mint())
            owner = Pubkey.from_string(self.address)

            resp = await self._client.get_token_accounts_by_owner(
                owner,
                {"mint": mint},
            )
            accounts = resp.value
            if not accounts:
                return Decimal("0")

            # Sum all associated token accounts (usually just one)
            total = Decimal("0")
            for acct in accounts:
                amount_resp = await self._client.get_token_account_balance(
                    acct.pubkey
                )
                ui_amount = amount_resp.value.ui_amount or 0
                total += Decimal(str(ui_amount))
            return total
        except Exception as exc:
            logger.error("Solana USDC balance failed: %s", exc)
            return Decimal("0")

    async def get_balance(self, asset: str = "usdc") -> Decimal:
        """Unified balance query. asset='usdc'|'sol'"""
        if asset == "sol":
            return await self.get_sol_balance()
        return await self.get_usdc_balance()

    # ── mutations ─────────────────────────────────────────────────────────────

    async def send_sol(self, to: str, amount_sol: Decimal) -> str:
        """Transfer SOL. Returns transaction signature."""
        if not self.is_connected:
            raise RuntimeError("Solana wallet not connected")

        if not _SOL_ADDR_RE.match(to):
            raise ValueError(f"Invalid Solana destination address: {to!r}")

        await require_approval(AuditAction(
            action_type="transaction",
            title=f"Send {amount_sol} SOL on Solana",
            details={
                "from": self.address,
                "to": to,
                "amount": str(amount_sol),
                "asset": "SOL",
                "rpc": settings.solana_rpc_url,
            },
            risk="high",
        ))

        try:
            from solders.pubkey import Pubkey  # type: ignore[import]
            from solders.system_program import TransferParams, transfer  # type: ignore[import]
            from solana.transaction import Transaction  # type: ignore[import]

            lamports = int(amount_sol * LAMPORTS_PER_SOL)
            ix = transfer(TransferParams(
                from_pubkey=self._keypair.pubkey(),
                to_pubkey=Pubkey.from_string(to),
                lamports=lamports,
            ))
            txn = Transaction().add(ix)
            resp = await self._client.send_transaction(txn, self._keypair)
            sig = str(resp.value)
            logger.info("Sent %s SOL to %s | sig: %s", amount_sol, to, sig)
            return sig
        except Exception as exc:
            logger.error("SOL transfer failed: %s", exc)
            raise

    async def send_usdc(self, to: str, amount: Decimal) -> str:
        """Transfer USDC (SPL token). Returns transaction signature."""
        if not self.is_connected:
            raise RuntimeError("Solana wallet not connected")

        if not _SOL_ADDR_RE.match(to):
            raise ValueError(f"Invalid Solana destination address: {to!r}")

        cap = settings.max_single_transfer_usdc
        if amount > cap:
            raise ValueError(f"Transfer amount {amount} exceeds single-transaction cap {cap}")

        await require_approval(AuditAction(
            action_type="transaction",
            title=f"Send {amount} USDC on Solana",
            details={
                "from": self.address,
                "to": to,
                "amount": str(amount),
                "asset": "USDC (SPL)",
                "mint": _usdc_mint(),
                "rpc": settings.solana_rpc_url,
            },
            risk="high",
        ))

        try:
            from solders.pubkey import Pubkey  # type: ignore[import]
            from spl.token.async_client import AsyncToken  # type: ignore[import]
            from spl.token.constants import TOKEN_PROGRAM_ID  # type: ignore[import]
            from spl.token.instructions import transfer_checked, TransferCheckedParams  # type: ignore[import]
            from solana.transaction import Transaction  # type: ignore[import]

            mint = Pubkey.from_string(_usdc_mint())
            owner = self._keypair.pubkey()
            dest = Pubkey.from_string(to)

            # Derive associated token accounts
            from spl.token._layouts import ACCOUNT_LAYOUT  # type: ignore[import]
            token = AsyncToken(self._client, mint, TOKEN_PROGRAM_ID, self._keypair)
            src_ata = await token.get_accounts_by_owner(owner)
            dst_ata = await token.get_or_create_associated_account_info(dest)

            if not src_ata.value:
                raise RuntimeError("No USDC token account found for sender")

            amount_raw = int(amount * Decimal(10 ** USDC_DECIMALS))
            ix = transfer_checked(TransferCheckedParams(
                program_id=TOKEN_PROGRAM_ID,
                source=src_ata.value[0].pubkey,
                mint=mint,
                dest=dst_ata.pubkey,
                owner=owner,
                amount=amount_raw,
                decimals=USDC_DECIMALS,
                signers=[],
            ))
            txn = Transaction().add(ix)
            resp = await self._client.send_transaction(txn, self._keypair)
            sig = str(resp.value)
            logger.info("Sent %s USDC to %s | sig: %s", amount, to, sig)
            return sig
        except Exception as exc:
            logger.error("USDC transfer failed: %s", exc)
            raise

    async def request_airdrop(self, sol_amount: float = 1.0) -> str:
        """Request devnet SOL airdrop."""
        if "mainnet" in settings.solana_rpc_url:
            raise RuntimeError("Airdrop only available on devnet/testnet")
        if not self.is_connected:
            raise RuntimeError("Solana wallet not connected")
        try:
            from solders.pubkey import Pubkey  # type: ignore[import]
            lamports = int(sol_amount * LAMPORTS_PER_SOL)
            resp = await self._client.request_airdrop(
                Pubkey.from_string(self.address), lamports
            )
            sig = str(resp.value)
            logger.info("Airdrop %s SOL requested | sig: %s", sol_amount, sig)
            return sig
        except Exception as exc:
            logger.error("Airdrop failed: %s", exc)
            raise
