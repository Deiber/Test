"""Push the issue branch and open a pull request that GitHub links to the issue."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

Run = Callable[..., subprocess.CompletedProcess[str]]


class GitHubPublisher:
    def __init__(self, repo_slug: str, run: Run = subprocess.run) -> None:
        self.repo_slug = repo_slug
        self._run = run

    def publish(
        self,
        *,
        repo: Path,
        branch: str,
        base_ref: str,
        title: str,
        body: str,
        issue_number: int,
    ) -> str:
        self._run(
            ["git", "push", "--set-upstream", "origin", branch],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
        existing = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self.repo_slug,
                "--head",
                branch,
                "--json",
                "url",
                "--jq",
                ".[0].url",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
        url = (existing.stdout or "").strip()
        if not url:
            created = self._run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    self.repo_slug,
                    "--base",
                    base_ref,
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    body,
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            )
            url = (created.stdout or "").strip()
        self.comment(issue_number, f"Opened {url} for this issue.")
        return url

    def comment(self, issue_number: int, body: str) -> None:
        self._run(
            [
                "gh",
                "issue",
                "comment",
                str(issue_number),
                "--repo",
                self.repo_slug,
                "--body",
                body,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
