from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"

    # ── Coinbase CDP ──────────────────────────────────────────────────────────
    cdp_api_key_name: str = ""
    cdp_api_key_private_key: str = ""
    network_id: str = "base-sepolia"

    # ── Agent behavior ────────────────────────────────────────────────────────
    scan_interval_minutes: int = 15
    min_trade_usdc: Decimal = Decimal("10")
    max_infra_spend_pct: float = 0.10
    profit_reinvest_pct: float = 0.70
    log_level: str = "INFO"
    # Require human approval before every real-world action (sends, containers, trades)
    audit_mode: bool = False

    # ── Infrastructure ────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    sqlite_path: Path = Path("./data/rothbard.db")
    wallet_path: Path = Path("~/.rothbard/wallet.json")

    # ── Solana ────────────────────────────────────────────────────────────────
    # mainnet-beta RPC: https://api.mainnet-beta.solana.com
    # devnet RPC:       https://api.devnet.solana.com
    solana_rpc_url: str = "https://api.devnet.solana.com"
    solana_keypair_path: Path = Path("~/.rothbard/solana_keypair.json")

    # ── x402 ─────────────────────────────────────────────────────────────────
    x402_port: int = 8402
    x402_price_usdc: Decimal = Decimal("0.01")

    @field_validator("wallet_path", "solana_keypair_path", mode="before")
    @classmethod
    def expand_wallet_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser()

    @field_validator("sqlite_path", mode="before")
    @classmethod
    def expand_sqlite_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser()

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def is_testnet(self) -> bool:
        return "sepolia" in self.network_id or "testnet" in self.network_id


# Singleton — import and use `settings` everywhere
settings = Settings()
