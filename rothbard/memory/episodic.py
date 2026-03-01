"""Episodic memory — SQLite-backed event ledger.

Stores every action, outcome, and ledger entry the agent takes across
restarts so it can learn from its own history.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Sequence

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rothbard.config import settings

logger = logging.getLogger(__name__)

_engine = None
async_session: async_sessionmaker[AsyncSession] = None  # type: ignore[assignment]


class Base(DeclarativeBase):
    pass


class Episode(Base):
    """One cycle of the agent loop — decision + outcome."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cycle: Mapped[int] = mapped_column(default=0)
    strategy: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(128), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="")  # success|failure|skip
    profit_usdc: Mapped[str] = mapped_column(String(32), default="0")
    details: Mapped[str] = mapped_column(Text, default="")


class LedgerEntry(Base):
    """Financial transaction record used by Treasury."""

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str] = mapped_column(String(64))
    amount_usdc: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))  # credit | debit
    strategy: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[str] = mapped_column(Text, default="")


class PendingPR(Base):
    """A GitHub PR opened by the agent, awaiting bounty payment."""

    __tablename__ = "pending_prs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pr_url: Mapped[str] = mapped_column(String(512), unique=True)
    repo: Mapped[str] = mapped_column(String(256))
    issue_number: Mapped[int] = mapped_column(Integer)
    expected_bounty_usdc: Mapped[str] = mapped_column(String(32), default="0")
    branch: Mapped[str] = mapped_column(String(256), default="")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|merged|closed


# ── setup ─────────────────────────────────────────────────────────────────────


async def init_db() -> None:
    global _engine, async_session

    db_url = f"sqlite+aiosqlite:///{settings.sqlite_path}"
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Episodic DB ready at %s", settings.sqlite_path)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


# ── helpers ───────────────────────────────────────────────────────────────────


async def record_episode(
    cycle: int,
    strategy: str,
    action: str,
    outcome: str,
    profit_usdc: str = "0",
    details: str = "",
) -> None:
    async with async_session() as session:
        ep = Episode(
            ts=datetime.now(timezone.utc),
            cycle=cycle,
            strategy=strategy,
            action=action,
            outcome=outcome,
            profit_usdc=profit_usdc,
            details=details,
        )
        session.add(ep)
        await session.commit()


async def recent_episodes(n: int = 20) -> Sequence[Episode]:
    async with async_session() as session:
        result = await session.execute(
            select(Episode).order_by(Episode.ts.desc()).limit(n)
        )
        return result.scalars().all()


async def record_pr(
    pr_url: str,
    repo: str,
    issue_number: int,
    expected_bounty_usdc: str,
    branch: str,
) -> None:
    async with async_session() as session:
        pr = PendingPR(
            pr_url=pr_url,
            repo=repo,
            issue_number=issue_number,
            expected_bounty_usdc=expected_bounty_usdc,
            branch=branch,
            opened_at=datetime.now(timezone.utc),
            status="open",
        )
        session.add(pr)
        await session.commit()


async def get_open_prs() -> Sequence[PendingPR]:
    async with async_session() as session:
        result = await session.execute(
            select(PendingPR).where(PendingPR.status == "open")
        )
        return result.scalars().all()


async def mark_pr_status(pr_url: str, status: str) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(PendingPR).where(PendingPR.pr_url == pr_url)
        )
        pr = result.scalar_one_or_none()
        if pr:
            pr.status = status
            await session.commit()


async def episodes_for_strategy(strategy: str, n: int = 10) -> Sequence[Episode]:
    async with async_session() as session:
        result = await session.execute(
            select(Episode)
            .where(Episode.strategy == strategy)
            .order_by(Episode.ts.desc())
            .limit(n)
        )
        return result.scalars().all()
