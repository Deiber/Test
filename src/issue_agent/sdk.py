"""Python kit for starting a coding agent on ready GitHub issues.

Pass an issue URL, or ask the kit to find open issues. Work starts only when
the issue carries the ready label (``ai-coding-ready`` by default).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Protocol, Sequence

from issue_agent.github import GitHubError, GitHubIssues
from issue_agent.issues import Issue, IssueRef, has_label, parse_issue
from issue_agent.publish import GitHubPublisher
from issue_agent.runner import Publisher, Result, implement, parse_command

READY_LABEL = "ai-coding-ready"


class IssueSource(Protocol):
    def get(self, ref: IssueRef) -> Issue: ...

    def list_open(self, repo: str, label: str) -> list[Issue]: ...


class IssueCoding:
    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        repo: str | None = None,
        repo_dir: str | Path = ".",
        label: str = READY_LABEL,
        base_ref: str = "main",
        token: str | None = None,
        github: IssueSource | None = None,
        publisher: Publisher | None = None,
    ) -> None:
        self.command = parse_command(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("A coding agent command is required")
        self.repo = repo.strip() if repo else None
        self.repo_dir = Path(repo_dir)
        self.label = label.strip() or READY_LABEL
        self.base_ref = base_ref.strip() or "main"
        self._token = token
        self._github = github
        self.publisher = publisher

    def work(self, issue: str) -> Result:
        """Fetch one issue URL and start the agent when it has the ready label."""
        ref = parse_issue(issue, default_repo=self.repo)
        self._require_same_repo(ref.slug)
        loaded = self.github.get(ref)
        return self.work_issue(loaded)

    def work_open_issues(self, repo: str | None = None) -> list[Result]:
        """Find open issues with the ready label and start the agent on each."""
        slug = (repo or self.repo or "").strip()
        if not slug:
            raise ValueError("repo is required to look for open issues")
        self._require_same_repo(slug)
        found = sorted(self.github.list_open(slug, self.label), key=lambda issue: issue.number)
        return [self.work_issue(issue) for issue in found]

    def work_issue(self, issue: Issue) -> Result:
        """Start the agent for an issue that is already loaded."""
        reason = self._skip_reason(issue)
        if reason is not None:
            return Result(status="skipped", detail=reason)
        self._checkout_base()
        slug = issue.repo or self.repo
        if not slug:
            raise ValueError("repo is required")
        publisher = self.publisher or GitHubPublisher(slug)
        return implement(
            repo=self.repo_dir,
            issue=issue,
            command=self.command,
            publisher=publisher,
            base_ref=self.base_ref,
        )

    @property
    def github(self) -> IssueSource:
        if self._github is not None:
            return self._github
        token = (self._token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
        if not token:
            raise GitHubError("Set GITHUB_TOKEN or GH_TOKEN to read issues.")
        self._github = GitHubIssues(token)
        return self._github

    def _skip_reason(self, issue: Issue) -> str | None:
        if issue.is_pull_request:
            return "pull request"
        if issue.author_type.casefold() == "bot":
            return "issue author is a bot"
        if not has_label(issue.labels, self.label):
            return f"missing label {self.label}"
        return None

    def _require_same_repo(self, slug: str) -> None:
        if self.repo and slug.casefold() != self.repo.casefold():
            raise ValueError(f"Issue is in {slug}; this kit is bound to {self.repo}")

    def _checkout_base(self) -> None:
        completed = subprocess.run(
            ["git", "checkout", self.base_ref],
            cwd=self.repo_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"git checkout {self.base_ref} failed: {detail}")
