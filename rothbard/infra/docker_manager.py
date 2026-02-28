"""DockerManager — spawn and manage ephemeral worker containers.

Workers are short-lived containers that execute a single task (defined in
TASK_JSON env var) and write their result as JSON to stdout on exit.

The manager mounts the host Docker socket so containers can be launched
from within the core container itself.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_WORKER_IMAGE = "rothbard-worker:latest"
CONTAINER_PREFIX = "rothbard-worker-"


@dataclass
class WorkerTask:
    task_id: str
    strategy: str
    payload: dict[str, Any] = field(default_factory=dict)
    budget_usdc: Decimal = Decimal("1")


@dataclass
class WorkerResult:
    task_id: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    exit_code: int = 0


class DockerManager:
    """Manages ephemeral Docker worker containers."""

    def __init__(self) -> None:
        self._client = None
        self._active: dict[str, str] = {}  # task_id → container_id

    def _get_client(self):
        if self._client is None:
            try:
                import docker  # type: ignore[import]
                self._client = docker.from_env()
                logger.info("Docker client connected")
            except Exception as exc:
                logger.error("Docker not available: %s", exc)
                raise
        return self._client

    def spawn_worker(
        self,
        task: WorkerTask,
        image: str = DEFAULT_WORKER_IMAGE,
        cpu_limit: float = 0.5,
        mem_limit: str = "256m",
    ) -> str:
        """Spawn a worker container. Returns container ID."""
        client = self._get_client()

        env = {
            "TASK_JSON": json.dumps({
                "task_id": task.task_id,
                "strategy": task.strategy,
                "payload": task.payload,
                "budget_usdc": str(task.budget_usdc),
            }),
            "LOG_LEVEL": "INFO",
        }

        name = f"{CONTAINER_PREFIX}{task.task_id}"

        try:
            container = client.containers.run(
                image=image,
                name=name,
                environment=env,
                detach=True,
                remove=False,  # keep for log collection
                cpu_period=100_000,
                cpu_quota=int(cpu_limit * 100_000),
                mem_limit=mem_limit,
                network_mode="bridge",
            )
            self._active[task.task_id] = container.id
            logger.info("Spawned worker %s (container %s)", task.task_id, container.short_id)
            return container.id
        except Exception as exc:
            logger.error("Failed to spawn worker %s: %s", task.task_id, exc)
            raise

    def wait_for_worker(self, task_id: str, timeout: int = 300) -> WorkerResult:
        """Block until the worker container exits, then return its result."""
        container_id = self._active.get(task_id)
        if not container_id:
            return WorkerResult(task_id=task_id, success=False, error="Container not found")

        client = self._get_client()

        try:
            container = client.containers.get(container_id)
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)

            logs = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")

            # Parse last JSON line from stdout as result
            output = {}
            for line in reversed(logs.strip().split("\n")):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        output = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            success = exit_code == 0
            container.remove(force=True)
            del self._active[task_id]

            logger.info("Worker %s finished (exit=%d)", task_id, exit_code)
            return WorkerResult(
                task_id=task_id,
                success=success,
                output=output,
                exit_code=exit_code,
            )
        except Exception as exc:
            logger.error("Worker %s wait failed: %s", task_id, exc)
            return WorkerResult(task_id=task_id, success=False, error=str(exc))

    def kill_worker(self, task_id: str) -> None:
        container_id = self._active.get(task_id)
        if not container_id:
            return
        try:
            client = self._get_client()
            container = client.containers.get(container_id)
            container.kill()
            container.remove(force=True)
            del self._active[task_id]
            logger.info("Killed worker %s", task_id)
        except Exception as exc:
            logger.warning("Failed to kill worker %s: %s", task_id, exc)

    def list_active(self) -> list[dict]:
        return [{"task_id": tid, "container_id": cid} for tid, cid in self._active.items()]

    def cleanup_dead(self) -> None:
        """Remove any containers that exited without being collected."""
        try:
            client = self._get_client()
            dead = client.containers.list(
                filters={"name": CONTAINER_PREFIX, "status": "exited"}
            )
            for c in dead:
                c.remove()
                logger.debug("Cleaned up dead container %s", c.short_id)
        except Exception as exc:
            logger.debug("Cleanup skipped: %s", exc)
