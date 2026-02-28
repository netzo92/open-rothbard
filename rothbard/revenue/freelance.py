"""FreelanceStrategy — bid on and complete microtasks autonomously.

Uses Claude to generate deliverables for tasks found by the UpworkSource.
Workers are spawned via DockerManager for parallelism when needed.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from anthropic import AsyncAnthropic

from rothbard.config import settings
from rothbard.markets.sources.base import Opportunity
from rothbard.revenue.base import ExecutionResult, RevenueStrategy
from rothbard.revenue.registry import register

logger = logging.getLogger(__name__)

MAX_DELIVERABLE_TOKENS = 2000


@register
class FreelanceStrategy(RevenueStrategy):
    name = "freelance"
    min_capital = Decimal("0.50")

    async def execute(self, opportunity: Opportunity, wallet) -> ExecutionResult:
        payload = opportunity.payload
        url = payload.get("url", "")
        platform = payload.get("platform", "unknown")

        # Fetch full task description
        task_description = await self._fetch_task(url) if url else opportunity.description

        # Generate deliverable using Claude
        deliverable = await self._generate_deliverable(
            task_title=opportunity.title,
            task_description=task_description,
        )

        if not deliverable:
            return ExecutionResult(success=False, details="Failed to generate deliverable")

        logger.info(
            "FreelanceStrategy: generated deliverable for '%s' (%d chars)",
            opportunity.title[:60], len(deliverable),
        )

        # NOTE: Submitting the deliverable back to the platform requires
        # platform-specific API integration (Upwork OAuth, etc.).
        # This is the integration point. Deliverable is logged for now.
        logger.debug("Deliverable: %s", deliverable[:500])

        # Assume successful bid/submission for simulation
        # Real implementation: await platform_api.submit(url, deliverable)
        estimated_revenue = opportunity.expected_revenue_usdc
        cost = Decimal("0.10")  # Claude API cost estimate
        profit = estimated_revenue - cost

        return ExecutionResult(
            success=True,
            profit_usdc=max(profit, Decimal("0")),
            details=(
                f"Generated {len(deliverable)}-char deliverable for {platform} task: "
                f"'{opportunity.title[:60]}'"
            ),
        )

    async def _fetch_task(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text[:3000]
        except Exception:
            return ""

    async def _generate_deliverable(
        self,
        task_title: str,
        task_description: str,
    ) -> str | None:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            message = await client.messages.create(
                model=settings.llm_model,
                max_tokens=MAX_DELIVERABLE_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Complete the following freelance task to the best of your ability.\n\n"
                            f"Task: {task_title}\n\n"
                            f"Details: {task_description[:2000]}\n\n"
                            "Provide a complete, professional deliverable."
                        ),
                    }
                ],
            )
            return message.content[0].text
        except Exception as exc:
            logger.error("Claude generation failed: %s", exc)
            return None
