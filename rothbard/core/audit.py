"""Audit mode — human-in-the-loop approval gate.

When AUDIT_MODE=true every real-world action (wallet sends, container
spawns, strategy executions) pauses and prints a rich summary to the
terminal. The operator types 'y' to approve or 'n' to deny.

All decisions (approved and denied) are appended as newline-delimited
JSON to data/audit.log for post-hoc review.

Usage
-----
    from rothbard.core.audit import require_approval, AuditAction

    await require_approval(AuditAction(
        action_type="transaction",
        title="Send 5.00 USDC on Base",
        details={"to": "0xabc...", "amount": "5.00", "asset": "USDC"},
        risk="medium",
    ))
    # raises AuditDenied if user types 'n'
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from rothbard.config import settings

logger = logging.getLogger(__name__)
_console = Console()

AUDIT_LOG_PATH = Path("./data/audit.log")


class AuditDenied(Exception):
    """Raised when the operator rejects a proposed action."""


@dataclass
class AuditAction:
    action_type: str          # "transaction" | "container" | "strategy" | "api_call"
    title: str                # one-line human summary
    details: dict[str, Any] = field(default_factory=dict)
    risk: str = "medium"      # "low" | "medium" | "high"


# ── pending dashboard approvals ───────────────────────────────────────────────

# Maps approval_id → (AuditAction, asyncio.Future[bool])
# Populated when running non-interactively; resolved by the dashboard API.
_pending: dict[str, tuple[AuditAction, asyncio.Future]] = {}


def _is_interactive() -> bool:
    """Return True if stdin is a real TTY (interactive terminal)."""
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def get_pending_approvals() -> list[dict]:
    """Return serialisable list of pending approvals for the dashboard."""
    return [
        {
            "id": aid,
            "action_type": action.action_type,
            "title": action.title,
            "details": action.details,
            "risk": action.risk,
        }
        for aid, (action, _) in list(_pending.items())
    ]


def resolve_approval(approval_id: str, approved: bool) -> bool:
    """Resolve a pending dashboard approval. Returns False if ID not found."""
    if approval_id not in _pending:
        return False
    action, future = _pending.pop(approval_id)
    if not future.done():
        future.set_result(approved)
    return True


# ── internal helpers ──────────────────────────────────────────────────────────


_RISK_COLOR = {"low": "green", "medium": "yellow", "high": "red"}
_TYPE_ICON  = {
    "transaction": "💸",
    "container":   "🐳",
    "strategy":    "📈",
    "api_call":    "🌐",
}


def _render_panel(action: AuditAction) -> Panel:
    icon = _TYPE_ICON.get(action.action_type, "⚡")
    risk_color = _RISK_COLOR.get(action.risk, "yellow")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold dim", no_wrap=True)
    table.add_column()

    table.add_row("Type", action.action_type.upper())
    table.add_row("Risk", Text(action.risk.upper(), style=f"bold {risk_color}"))

    for key, val in action.details.items():
        table.add_row(key.replace("_", " ").title(), str(val))

    return Panel(
        table,
        title=f"{icon}  [bold]{action.title}[/bold]",
        title_align="left",
        border_style=risk_color,
        padding=(1, 2),
    )


async def _async_input(prompt: str) -> str:
    """Non-blocking stdin read that doesn't freeze the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input, prompt)


def _append_audit_log(action: AuditAction, approved: bool) -> None:
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action_type": action.action_type,
            "title": action.title,
            "risk": action.risk,
            "details": action.details,
            "approved": approved,
        }
        with AUDIT_LOG_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)


# ── public API ────────────────────────────────────────────────────────────────


async def require_approval(action: AuditAction) -> None:
    """Gate a real-world action behind operator approval.

    No-op when AUDIT_MODE is false.  Raises AuditDenied if denied.

    Approval channel (automatic):
    - Interactive TTY  → terminal stdin prompt (original behaviour)
    - Non-interactive  → registers action in _pending dict and waits up to
                         5 minutes for the dashboard operator to click
                         Approve / Deny at /dashboard.
    """
    if not settings.audit_mode:
        return

    _console.print()
    _console.print(_render_panel(action))
    _console.print()

    if _is_interactive():
        # ── CLI path ──────────────────────────────────────────────────────────
        try:
            answer = await _async_input("  Approve? [y/N] > ")
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        approved = answer.strip().lower() in {"y", "yes"}
    else:
        # ── Dashboard path ────────────────────────────────────────────────────
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()
        _pending[approval_id] = (action, future)
        logger.info(
            "[AUDIT] Waiting for dashboard approval (id=%s): %s",
            approval_id[:8], action.title,
        )
        try:
            approved = await asyncio.wait_for(future, timeout=300.0)  # 5 min
        except asyncio.TimeoutError:
            _pending.pop(approval_id, None)
            approved = False
            logger.warning("[AUDIT] Dashboard approval timed out: %s", action.title)

    _append_audit_log(action, approved)

    if approved:
        logger.info("[AUDIT] Approved: %s", action.title)
    else:
        logger.warning("[AUDIT] Denied: %s", action.title)
        raise AuditDenied(f"Operator denied: {action.title}")
