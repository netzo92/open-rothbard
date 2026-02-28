"""Worker entrypoint — runs inside the ephemeral Docker container.

Reads TASK_JSON from environment, executes the task, prints a JSON
result to stdout, then exits. Exit code 0 = success, 1 = failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys


def get_task() -> dict:
    raw = os.environ.get("TASK_JSON", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"success": False, "error": f"Invalid TASK_JSON: {exc}"}))
        sys.exit(1)


async def run_freelance_task(task: dict) -> dict:
    """Complete a freelance task using Claude."""
    import anthropic

    payload = task.get("payload", {})
    description = payload.get("description", "")
    title = payload.get("title", "Unknown task")

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"Complete this task:\n\nTitle: {title}\n\nDetails: {description}\n\nProvide a complete deliverable.",
        }],
    )
    return {"success": True, "deliverable": message.content[0].text}


async def run_content_task(task: dict) -> dict:
    """Generate content."""
    import anthropic

    payload = task.get("payload", {})
    topic = payload.get("topic", "general technology")
    intent = payload.get("intent", "informative article")

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": f"Write a {intent} about: {topic}. Markdown format, 800-1200 words.",
        }],
    )
    return {"success": True, "content": message.content[0].text}


async def main() -> None:
    task = get_task()
    strategy = task.get("strategy", "unknown")

    handlers = {
        "freelance": run_freelance_task,
        "content": run_content_task,
    }

    handler = handlers.get(strategy)
    if not handler:
        result = {"success": False, "error": f"Unknown strategy: {strategy}"}
    else:
        try:
            result = await handler(task)
        except Exception as exc:
            result = {"success": False, "error": str(exc)}

    print(json.dumps(result))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    asyncio.run(main())
