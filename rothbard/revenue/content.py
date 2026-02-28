"""ContentStrategy — generate SEO/affiliate content and publish it."""
from __future__ import annotations

import logging
from decimal import Decimal

from anthropic import AsyncAnthropic

from rothbard.config import settings
from rothbard.markets.sources.base import Opportunity
from rothbard.revenue.base import ExecutionResult, RevenueStrategy
from rothbard.revenue.registry import register

logger = logging.getLogger(__name__)

ARTICLE_MAX_TOKENS = 1500


@register
class ContentStrategy(RevenueStrategy):
    name = "content"
    min_capital = Decimal("0.10")

    async def execute(self, opportunity: Opportunity, wallet) -> ExecutionResult:
        payload = opportunity.payload
        content_type = payload.get("type", "affiliate")

        if content_type == "affiliate":
            niche = payload.get("niche", "technology")
            article = await self._generate_article(
                topic=f"Best {niche} tools and services in 2026",
                intent="SEO review article with affiliate links",
            )
        else:
            topic = payload.get("topic", "trending news")
            article = await self._generate_article(
                topic=topic,
                intent="informative news-style article for display ad revenue",
            )

        if not article:
            return ExecutionResult(success=False, details="Content generation failed")

        # NOTE: Publishing requires integration with Ghost, WordPress, Medium,
        # or a static site generator. This is the integration point.
        # For now we log and save locally.
        output_path = f"./data/content_{opportunity.id}.md"
        try:
            import os
            os.makedirs("./data", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(article)
            logger.info("Content saved to %s (%d chars)", output_path, len(article))
        except Exception as exc:
            logger.warning("Could not save content: %s", exc)

        cost = Decimal("0.10")
        # Revenue is probabilistic; use the opportunity estimate
        estimated_revenue = opportunity.expected_revenue_usdc

        return ExecutionResult(
            success=True,
            profit_usdc=max(estimated_revenue - cost, Decimal("0")),
            details=(
                f"Generated {len(article)}-char {content_type} article for: "
                f"'{opportunity.title[:60]}'"
            ),
        )

    async def _generate_article(self, topic: str, intent: str) -> str | None:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            message = await client.messages.create(
                model=settings.llm_model,
                max_tokens=ARTICLE_MAX_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Write a high-quality {intent} about: {topic}\n\n"
                            "Requirements:\n"
                            "- 800-1200 words\n"
                            "- SEO-optimized with natural keyword usage\n"
                            "- Markdown format\n"
                            "- Clear headings and structure\n"
                            "- Include a compelling intro and actionable conclusion"
                        ),
                    }
                ],
            )
            return message.content[0].text
        except Exception as exc:
            logger.error("Content generation failed: %s", exc)
            return None
