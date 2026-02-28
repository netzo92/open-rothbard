"""Generic authenticated API caller for agent tools."""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def call_api(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: Any = None,
    bearer_token: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Make an authenticated HTTP call and return the parsed JSON response."""
    _headers = headers or {}
    if bearer_token:
        _headers["Authorization"] = f"Bearer {bearer_token}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method=method.upper(),
            url=url,
            headers=_headers,
            params=params,
            json=json,
        )
        response.raise_for_status()
        return response.json()
