"""Strategy plugin registry.

Strategies self-register by decorating their class with @register.
Import all strategy modules to trigger registration.
"""
from __future__ import annotations

import logging
from typing import Type

from rothbard.revenue.base import RevenueStrategy

logger = logging.getLogger(__name__)

_registry: dict[str, Type[RevenueStrategy]] = {}


def register(cls: Type[RevenueStrategy]) -> Type[RevenueStrategy]:
    """Decorator: register a strategy class by its .name attribute."""
    _registry[cls.name] = cls
    logger.debug("Registered strategy: %s", cls.name)
    return cls


def get_strategy(name: str) -> RevenueStrategy | None:
    cls = _registry.get(name)
    return cls() if cls else None


def get_all_strategies() -> list[RevenueStrategy]:
    return [cls() for cls in _registry.values()]


def _load_all() -> None:
    """Import all strategy modules to trigger their @register decorators."""
    from rothbard.revenue import arbitrage, content, freelance, trading  # noqa: F401
