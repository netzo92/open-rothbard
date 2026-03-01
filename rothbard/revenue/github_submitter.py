"""GitHubSubmitter — forks a repo, commits a Claude-generated fix, opens a PR.

Requires GITHUB_TOKEN with `repo` scope in .env.

Pipeline:
  1. Fetch full issue from GitHub API
  2. Fork the repo under the bot's account (idempotent)
  3. Fetch relevant source files for context
  4. Ask Claude to generate file changes
  5. Create a branch on the fork
  6. Commit each changed file
  7. Open a PR against the upstream repo
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

import httpx
from anthropic import AsyncAnthropic

from rothbard.config import settings
from rothbard.core.scrub import scrub

logger = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_CODE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".h", ".md"}
_MAX_FILE_CHARS = 3000
_MAX_CONTEXT_FILES = 8


class GitHubSubmitter:
    """Handles the full fork → fix → PR pipeline for a GitHub bounty issue."""

    def __init__(self) -> None:
        if not settings.github_token:
            raise RuntimeError(
                "GITHUB_TOKEN is required (with repo scope) to submit GitHub PRs."
            )
        self._headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def submit(self, repo: str, issue_number: int) -> dict:
        """
        Run the full pipeline.  Returns {"pr_url": str, "pr_number": int, "branch": str}.
        `repo` is "owner/repo-name".
        """
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            issue = await self._get(http, f"/repos/{repo}/issues/{issue_number}")
            repo_info = await self._get(http, f"/repos/{repo}")
            default_branch = repo_info["default_branch"]

            fork_name, just_created = await self._ensure_fork(http, repo)
            if just_created:
                # GitHub takes a few seconds to initialise a fresh fork
                await asyncio.sleep(6)

            files_context = await self._fetch_context(http, repo, issue)
            changes = await self._generate_fix(issue, files_context)
            if not changes:
                raise RuntimeError(
                    f"Claude could not generate a fix for {repo}#{issue_number}"
                )

            branch = f"fix/issue-{issue_number}"
            base_sha = await self._get_branch_sha(http, fork_name, default_branch)
            await self._create_branch(http, fork_name, branch, base_sha)

            for change in changes:
                await self._commit_file(http, fork_name, branch, change, issue_number)

            pr = await self._open_pr(http, repo, fork_name, branch, issue, changes)
            logger.info(
                "Opened PR %s for %s#%d", pr["html_url"], repo, issue_number
            )
            return {
                "pr_url": pr["html_url"],
                "pr_number": pr["number"],
                "branch": branch,
            }

    # ── low-level HTTP ────────────────────────────────────────────────────────

    async def _get(self, http: httpx.AsyncClient, path: str) -> dict:
        resp = await http.get(f"{_BASE}{path}", headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, http: httpx.AsyncClient, path: str, body: dict) -> dict:
        resp = await http.post(f"{_BASE}{path}", json=body, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def _put(self, http: httpx.AsyncClient, path: str, body: dict) -> dict:
        resp = await http.put(f"{_BASE}{path}", json=body, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    # ── pipeline steps ────────────────────────────────────────────────────────

    async def _ensure_fork(self, http: httpx.AsyncClient, repo: str) -> tuple[str, bool]:
        """Return (fork_full_name, just_created). Idempotent."""
        me = await self._get(http, "/user")
        my_login = me["login"]
        repo_name = repo.split("/")[1]
        fork_name = f"{my_login}/{repo_name}"

        try:
            await self._get(http, f"/repos/{fork_name}")
            return fork_name, False
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

        # Fork doesn't exist — create it
        fork = await self._post(http, f"/repos/{repo}/forks", {"default_branch_only": True})
        return fork["full_name"], True

    async def _get_branch_sha(self, http: httpx.AsyncClient, repo: str, branch: str) -> str:
        data = await self._get(http, f"/repos/{repo}/git/ref/heads/{branch}")
        return data["object"]["sha"]

    async def _create_branch(
        self, http: httpx.AsyncClient, repo: str, branch: str, sha: str
    ) -> None:
        try:
            await self._post(http, f"/repos/{repo}/git/refs", {
                "ref": f"refs/heads/{branch}",
                "sha": sha,
            })
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 422:
                pass  # Branch already exists — fine
            else:
                raise

    async def _fetch_context(
        self, http: httpx.AsyncClient, repo: str, issue: dict
    ) -> str:
        """Fetch the most relevant source files and return them as a single string."""
        try:
            tree = await self._get(http, f"/repos/{repo}/git/trees/HEAD?recursive=1")
            blobs = [
                item for item in tree.get("tree", [])
                if item["type"] == "blob"
                and any(item["path"].endswith(ext) for ext in _CODE_EXTENSIONS)
                and item.get("size", 0) < 60_000
            ]
        except Exception as exc:
            logger.warning("Could not fetch repo tree: %s", exc)
            return ""

        # Rank files by keyword overlap with the issue
        issue_words = set(re.findall(r"\w+", (
            (issue.get("title") or "") + " " + (issue.get("body") or "")
        ).lower()))

        def relevance(path: str) -> int:
            return len(issue_words & set(re.findall(r"\w+", path.lower())))

        top_files = sorted(blobs, key=lambda b: relevance(b["path"]), reverse=True)
        top_files = top_files[:_MAX_CONTEXT_FILES]

        parts: list[str] = []
        for item in top_files:
            try:
                file_data = await self._get(http, f"/repos/{repo}/contents/{item['path']}")
                raw = base64.b64decode(file_data["content"]).decode("utf-8", errors="replace")
                parts.append(f"### {item['path']}\n```\n{raw[:_MAX_FILE_CHARS]}\n```")
            except Exception:
                pass

        return "\n\n".join(parts)

    async def _generate_fix(
        self, issue: dict, files_context: str
    ) -> list[dict] | None:
        """Ask Claude to produce a list of file changes for this issue."""
        title = scrub(issue.get("title") or "", max_length=200)
        body = scrub(issue.get("body") or "", max_length=2000)

        prompt = (
            "You are an autonomous software agent fixing a GitHub issue.\n\n"
            f"Issue title: {title}\n"
            f"Issue body:\n{body}\n\n"
            f"Relevant source files:\n"
            f"{files_context[:6000] if files_context else '(none available)'}\n\n"
            "Return ONLY a JSON array (no markdown fences, no explanation) in this exact format:\n"
            '[{"path": "src/foo.py", "content": "<complete new file content>", '
            '"commit_message": "Fix: short description"}]\n\n'
            "Rules:\n"
            "- Include only files you actually need to change.\n"
            "- Write the COMPLETE new file content, not a diff.\n"
            "- Maximum 3 files.\n"
            "- If you cannot determine a safe, correct fix, return an empty array []."
        )

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        try:
            msg = await client.messages.create(
                model=settings.llm_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            # Strip accidental markdown fences
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.lower().startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0].strip()
            changes = json.loads(raw)
            if not isinstance(changes, list):
                return None
            # Validate minimal shape
            return [c for c in changes if "path" in c and "content" in c]
        except Exception as exc:
            logger.error("Failed to generate fix: %s", exc)
            return None

    async def _commit_file(
        self,
        http: httpx.AsyncClient,
        repo: str,
        branch: str,
        change: dict,
        issue_number: int,
    ) -> None:
        path = change["path"]
        content_b64 = base64.b64encode(change["content"].encode()).decode()
        message = change.get("commit_message", f"Fix issue #{issue_number}")

        body: dict = {"message": message, "content": content_b64, "branch": branch}

        # If the file already exists we need its SHA to update it
        try:
            existing = await self._get(
                http, f"/repos/{repo}/contents/{path}?ref={branch}"
            )
            body["sha"] = existing["sha"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            # File doesn't exist yet — no sha needed

        await self._put(http, f"/repos/{repo}/contents/{path}", body)

    async def _open_pr(
        self,
        http: httpx.AsyncClient,
        upstream: str,
        fork: str,
        branch: str,
        issue: dict,
        changes: list[dict],
    ) -> dict:
        fork_owner = fork.split("/")[0]
        issue_number = issue["number"]
        issue_title = issue.get("title", f"Issue #{issue_number}")
        files_changed = ", ".join(c["path"] for c in changes)
        upstream_info = await self._get(http, f"/repos/{upstream}")

        pr_body = (
            f"Closes #{issue_number}\n\n"
            f"This PR was opened autonomously in response to the bounty in "
            f"[#{issue_number}]({issue.get('html_url', '')}).\n\n"
            f"**Files changed:** `{files_changed}`\n\n"
            f"If you're happy with the fix, please merge and send the bounty to "
            f"the wallet address in my GitHub profile, or via the payment method "
            f"specified in the issue."
        )

        return await self._post(http, f"/repos/{upstream}/pulls", {
            "title": f"Fix: {issue_title[:100]}",
            "body": pr_body,
            "head": f"{fork_owner}:{branch}",
            "base": upstream_info["default_branch"],
            "maintainer_can_modify": True,
        })


async def check_pr_status(pr_url: str) -> str:
    """
    Poll a PR URL and return its current state: 'open' | 'merged' | 'closed'.
    Uses unauthenticated read if no token; authenticated if token available.
    """
    # Convert HTML URL → API URL
    # https://github.com/owner/repo/pull/42 → /repos/owner/repo/pulls/42
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url
    )
    if not match:
        return "open"

    owner, repo, number = match.groups()
    api_path = f"/repos/{owner}/{repo}/pulls/{number}"
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(f"{_BASE}{api_path}", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("merged"):
                return "merged"
            return data.get("state", "open")  # 'open' or 'closed'
    except Exception as exc:
        logger.warning("Could not check PR status for %s: %s", pr_url, exc)
        return "open"
