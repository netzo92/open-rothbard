"""Scout entrypoint — lightweight parallel market scanner worker."""
from __future__ import annotations

import asyncio
import json
import os
import sys


async def scan_defi() -> list[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://yields.llama.fi/pools")
            resp.raise_for_status()
            pools = resp.json().get("data", [])
        base_pools = [
            p for p in pools
            if p.get("chain") in {"Base", "base"}
            and (p.get("apy") or 0) >= 5.0
            and (p.get("tvlUsd") or 0) >= 100_000
        ]
        base_pools.sort(key=lambda p: p.get("apy", 0), reverse=True)
        return [{"project": p["project"], "symbol": p["symbol"], "apy": p["apy"]} for p in base_pools[:5]]
    except Exception as exc:
        return [{"error": str(exc)}]


async def main() -> None:
    target = os.environ.get("SCAN_TARGET", "defi")

    scanners = {
        "defi": scan_defi,
    }

    scanner = scanners.get(target)
    if not scanner:
        print(json.dumps({"success": False, "error": f"Unknown scan target: {target}"}))
        sys.exit(1)

    results = await scanner()
    print(json.dumps({"success": True, "results": results}))


if __name__ == "__main__":
    asyncio.run(main())
