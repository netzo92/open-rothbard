"""Web browsing and scraping tools available to worker agents."""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def fetch_text(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and return its text content."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "RothbardAgent/0.1"})
        resp.raise_for_status()
        return resp.text[:max_chars]


async def fetch_json(url: str, **kwargs) -> Any:
    """Fetch a URL and parse as JSON."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "RothbardAgent/0.1"}, **kwargs)
        resp.raise_for_status()
        return resp.json()


async def post_json(url: str, payload: dict, headers: dict | None = None) -> Any:
    """POST JSON to a URL and return the response."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload, headers=headers or {})
        resp.raise_for_status()
        return resp.json()
