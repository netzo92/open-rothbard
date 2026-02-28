"""x402 payment middleware — FastAPI router.

Implements a simplified version of the x402 protocol: HTTP 402 Payment
Required responses for premium endpoints. Callers (other agents or humans)
include a payment proof header; the server validates on-chain and serves
the response.

x402 spec: https://x402.org / Coinbase's HTTP 402 micropayment revival.
"""
from __future__ import annotations

import hashlib
import logging
import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from rothbard.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/x402", tags=["x402"])

# In-memory set of seen payment hashes (prevents replay attacks)
_seen_payments: set[str] = set()


def _payment_required_response(endpoint: str) -> JSONResponse:
    """Return HTTP 402 with x402 payment instructions."""
    return JSONResponse(
        status_code=402,
        content={
            "error": "Payment Required",
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": settings.network_id,
                    "maxAmountRequired": str(settings.x402_price_usdc),
                    "resource": endpoint,
                    "description": "Pay to access Rothbard agent intelligence",
                    "mimeType": "application/json",
                    "payTo": "0x0000000000000000000000000000000000000000",  # agent wallet address (set at runtime)
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
                    "extra": {
                        "name": "open-rothbard",
                        "version": "0.1.0",
                    },
                }
            ],
        },
        headers={"X-Payment": "required"},
    )


def _validate_payment(payment_header: str) -> bool:
    """Validate the x402 payment proof header.

    In production this would verify an on-chain transaction or signed
    EIP-712 payment message. Here we do basic structural validation.
    """
    if not payment_header:
        return False

    # Prevent replay
    ph = hashlib.sha256(payment_header.encode()).hexdigest()
    if ph in _seen_payments:
        logger.warning("Replay attack detected: payment hash %s", ph[:12])
        return False

    # Basic format check: expect base64-encoded JSON payload
    try:
        import base64
        import json
        decoded = json.loads(base64.b64decode(payment_header).decode())
        # Must have transaction hash and timestamp
        tx_hash = decoded.get("transaction_hash", "")
        ts = decoded.get("timestamp", 0)
        amount = Decimal(str(decoded.get("amount", "0")))

        if not tx_hash or not ts or amount < settings.x402_price_usdc:
            return False

        # Must be recent (within 5 minutes)
        if abs(time.time() - ts) > 300:
            return False

        _seen_payments.add(ph)
        return True
    except Exception:
        return False


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.get("/intelligence")
async def get_intelligence(
    request: Request,
    x_payment: str | None = Header(default=None),
) -> Any:
    """Premium endpoint: returns current market opportunities and agent analysis.

    Requires x402 USDC micropayment.
    """
    if not x_payment or not _validate_payment(x_payment):
        return _payment_required_response(str(request.url))

    # Return current agent state (market snapshot)
    from rothbard.markets.scanner import OpportunityScanner
    scanner = OpportunityScanner()
    opportunities = await scanner.scan_all()

    return {
        "opportunities": [
            {
                "id": o.id,
                "type": str(o.strategy_type),
                "title": o.title,
                "expected_roi_usdc": str(o.expected_roi),
                "risk_score": o.risk_score,
            }
            for o in opportunities[:10]
        ],
        "timestamp": time.time(),
    }


@router.get("/status")
async def get_status() -> dict:
    """Free endpoint: agent heartbeat and version info."""
    return {
        "status": "running",
        "version": "0.1.0",
        "network": settings.network_id,
        "x402_price_usdc": str(settings.x402_price_usdc),
    }
