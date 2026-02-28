"""open-rothbard entrypoint.

Wires together all subsystems and starts:
  1. SQLite episodic memory DB
  2. ChromaDB semantic memory
  3. CDP wallet (Base/EVM)
  4. Solana wallet
  5. FastAPI x402 payment server (background)
  6. The LangGraph agent loop
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from rich.logging import RichHandler

from rothbard.config import settings
from rothbard.core import nodes as core_nodes
from rothbard.core.agent import RothbardAgent
from rothbard.finance.treasury import Treasury
from rothbard.finance.solana_wallet import SolanaWallet
from rothbard.finance.wallet import Wallet
from rothbard.finance.x402 import router as x402_router
from rothbard.markets.scanner import OpportunityScanner
from rothbard.memory import episodic, semantic
from rothbard.revenue.registry import _load_all

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("rothbard")


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rothbard x402 server starting")
    yield
    logger.info("Rothbard x402 server stopping")


app = FastAPI(
    title="open-rothbard",
    description="Autonomous anarcho-capitalist economic agent",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(x402_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── startup ───────────────────────────────────────────────────────────────────


async def startup() -> tuple[Wallet, SolanaWallet, Treasury, OpportunityScanner]:
    logger.info("=" * 60)
    logger.info("  open-rothbard v0.1.0")
    logger.info("  EVM network:    %s", settings.network_id)
    logger.info("  Solana RPC:     %s", settings.solana_rpc_url)
    logger.info("  Scan interval:  %d min", settings.scan_interval_minutes)
    logger.info("=" * 60)

    # 1. Episodic memory (SQLite)
    await episodic.init_db()

    # 2. Semantic memory (ChromaDB)
    await semantic.init_semantic(settings.chroma_host, settings.chroma_port)

    # 3. EVM wallet (Base via CDP)
    wallet = Wallet()
    await wallet.connect()
    logger.info("EVM wallet:    %s", wallet.address)

    # 4. Testnet faucet for EVM on first run
    if settings.is_testnet:
        balance = await wallet.get_balance()
        if balance == 0:
            logger.info("Zero EVM balance — requesting faucet funds")
            try:
                await wallet.fund_from_faucet()
            except Exception as exc:
                logger.warning("EVM faucet failed: %s", exc)

    # 5. Solana wallet
    sol_wallet = SolanaWallet()
    await sol_wallet.connect()
    logger.info("Solana wallet: %s", sol_wallet.address)

    # Devnet airdrop on first run if balance is zero
    if "devnet" in settings.solana_rpc_url and sol_wallet.is_connected:
        sol_balance = await sol_wallet.get_sol_balance()
        if sol_balance == 0:
            logger.info("Zero SOL balance — requesting devnet airdrop")
            try:
                await sol_wallet.request_airdrop(sol_amount=1.0)
            except Exception as exc:
                logger.warning("Solana airdrop failed: %s", exc)

    # 6. Treasury
    treasury = Treasury()

    # 7. Market scanner (includes SolanaDeFiSource)
    scanner = OpportunityScanner()

    # 8. Revenue strategy plugins
    _load_all()

    # 9. Inject singletons into nodes module
    core_nodes.setup(wallet=wallet, treasury=treasury, scanner=scanner)

    return wallet, sol_wallet, treasury, scanner


async def run_agent() -> None:
    """Run the agent loop in the foreground."""
    agent = RothbardAgent()
    await agent.run()


async def run_server() -> None:
    """Run the FastAPI x402 server in the background."""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.x402_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    _, sol_wallet, __, ___ = await startup()

    # Run agent loop and HTTP server concurrently
    tasks = [
        asyncio.create_task(run_agent(), name="agent-loop"),
        asyncio.create_task(run_server(), name="x402-server"),
    ]

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: [t.cancel() for t in tasks])

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Shutting down gracefully...")
    finally:
        for task in tasks:
            task.cancel()
        await sol_wallet.close()
        logger.info("Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
