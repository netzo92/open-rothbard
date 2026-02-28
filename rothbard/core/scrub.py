"""Input sanitizer — strip prompt injection patterns from all external text.

Any text that originates outside the agent (RSS feeds, web pages, API
responses) must be passed through ``scrub()`` before being included in an
LLM prompt or stored in an Opportunity that will later reach the LLM.

Defense strategy
----------------
1. Decode HTML entities and strip HTML tags so markup cannot hide payloads.
2. Replace known injection trigger phrases with ``[FILTERED]`` so they are
   visible in logs but cannot execute.
3. Truncate to a configurable max length to prevent context-flooding.

This is one layer of defense-in-depth; it is combined with a strict Pydantic
output schema and destination-address validation in the wallet layer.
"""
from __future__ import annotations

import html
import re

# ---------------------------------------------------------------------------
# Injection pattern list
# ---------------------------------------------------------------------------
# Each entry is a compiled regex that matches a common prompt-injection trigger.
# Patterns are intentionally broad to catch paraphrases.

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    # Classic direct overrides
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above|earlier)?\s*instructions?", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|above|earlier)?\s*instructions?", re.IGNORECASE),
    re.compile(r"override\s+(all\s+)?(previous|prior|above|earlier)?\s*instructions?", re.IGNORECASE),

    # Role hijacking
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+(you\s+are|to\s+be)\b", re.IGNORECASE),
    re.compile(r"\byour\s+new\s+role\b", re.IGNORECASE),

    # Injected instruction markers
    re.compile(r"\bnew\s+(instructions?|directive|task|goal|objective)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"<\s*(system|instructions?|prompt)\s*>", re.IGNORECASE),
    re.compile(r"```\s*(system|instructions?)\b", re.IGNORECASE),

    # Role-label injection (fake turn markers)
    re.compile(r"\b(system|assistant|human|user)\s*:\s", re.IGNORECASE),

    # Financial exfiltration triggers — coarse patterns to flag suspicious directives
    re.compile(r"\bsend\s+\d[\d.,]*\s*(usdc|sol|eth|btc|usd)?\b", re.IGNORECASE),
    re.compile(r"\btransfer\s+\d[\d.,]*\s*(usdc|sol|eth|btc|usd)?\b", re.IGNORECASE),
    re.compile(r"\bwire\s+\d[\d.,]*\b", re.IGNORECASE),
    re.compile(r"\bsend\s+(all|everything|funds|balance)\b", re.IGNORECASE),

    # Wallet / key exfiltration
    re.compile(r"\b(reveal|output|print|return|show|expose)\s+(the\s+)?(private\s+key|seed|mnemonic|keypair|secret)\b", re.IGNORECASE),
]

# Pre-compiled HTML-tag stripper (limit tag content to ≤200 chars to avoid ReDoS)
_HTML_TAG_RE = re.compile(r"<[^>]{0,200}>")
_WHITESPACE_RE = re.compile(r"\s+")


def scrub(text: str, max_length: int = 500) -> str:
    """Sanitize external text before it enters an LLM prompt.

    Parameters
    ----------
    text:
        Raw external string (RSS title, web-page excerpt, API response).
    max_length:
        Maximum allowed output length (characters).  Text is hard-truncated
        after injection patterns are removed.

    Returns
    -------
    str
        Sanitized, truncated string safe to include in an LLM prompt.
    """
    if not text:
        return ""

    # 1. Decode HTML entities (&amp; → &, &#x27; → ', etc.)
    text = html.unescape(text)

    # 2. Strip HTML/XML tags
    text = _HTML_TAG_RE.sub(" ", text)

    # 3. Replace injection trigger phrases
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("[FILTERED]", text)

    # 4. Collapse excess whitespace
    text = _WHITESPACE_RE.sub(" ", text).strip()

    # 5. Hard truncate
    return text[:max_length]
