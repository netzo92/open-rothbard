"""Sandboxed code execution via ephemeral Docker containers.

Instead of running untrusted code in the main process, we spawn a
throwaway container, pass the code as an env var, capture stdout, and
destroy the container. Each execution is fully isolated.
"""
from __future__ import annotations

import json
import logging
import uuid

from rothbard.infra.docker_manager import DockerManager, WorkerTask

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "python:3.12-slim"
EXEC_TIMEOUT = 30  # seconds


async def run_python(code: str, inputs: dict | None = None) -> dict:
    """Execute Python code in a sandboxed container.

    The code receives `inputs` as a JSON-serializable dict in the variable
    `INPUTS` and should print a JSON result dict to stdout.

    Returns: {"success": bool, "output": any, "error": str}
    """
    manager = DockerManager()
    task_id = str(uuid.uuid4())[:8]

    # Wrap user code to inject inputs and capture result
    wrapped = f"""
import json, sys
INPUTS = {json.dumps(inputs or {})}
try:
{chr(10).join('    ' + line for line in code.strip().split(chr(10)))}
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
"""

    task = WorkerTask(
        task_id=task_id,
        strategy="code_exec",
        payload={"code": wrapped},
    )

    try:
        # Override: use python slim image, run the wrapped code directly
        import docker  # type: ignore[import]

        client = docker.from_env()
        container = client.containers.run(
            SANDBOX_IMAGE,
            command=["python3", "-c", wrapped],
            detach=True,
            remove=False,
            mem_limit="128m",
            network_mode="none",  # no network for sandboxed code
            read_only=True,
        )
        result = container.wait(timeout=EXEC_TIMEOUT)
        exit_code = result.get("StatusCode", -1)
        logs = container.logs(stdout=True).decode("utf-8", errors="replace").strip()
        container.remove(force=True)

        if exit_code != 0:
            return {"success": False, "error": logs}

        # Parse last JSON line
        for line in reversed(logs.split("\n")):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass

        return {"success": True, "output": logs}
    except Exception as exc:
        logger.error("Sandboxed exec failed: %s", exc)
        return {"success": False, "error": str(exc)}
