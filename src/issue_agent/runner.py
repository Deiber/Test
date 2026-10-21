"""Run a coding agent on the current checkout, then hand the branch to a publisher."""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from issue_agent.issues import Issue
from issue_agent.prompt import branch_name, build_prompt, pr_body, pr_title

_BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
_PROMPT_FILE_TOKEN = "{prompt_file}"


@dataclass(frozen=True)
class Result:
    status: str
    branch: str = ""
    pr_url: str | None = None
    detail: str = ""


class Publisher(Protocol):
    def publish(
        self,
        *,
        repo: Path,
        branch: str,
        base_ref: str,
        title: str,
        body: str,
        issue_number: int,
    ) -> str: ...

    def comment(self, issue_number: int, body: str) -> None: ...


def parse_command(raw: str) -> list[str]:
    """Split a command without expanding `{prompt_file}`. Expansion happens per run.

    The workflow runs on Linux, so the command string is parsed with POSIX rules.
    """
    return shlex.split(raw, posix=True)


def split_command(raw: str, prompt_file: Path) -> list[str]:
    file_path = str(prompt_file)
    return [part.replace(_PROMPT_FILE_TOKEN, file_path) for part in parse_command(raw)]


def implement(
    *,
    repo: Path,
    issue: Issue,
    command: Sequence[str],
    publisher: Publisher,
    base_ref: str,
) -> Result:
    """Edit `repo` with `command` and publish a linked pull request when code changed."""
    if issue.author_type.casefold() == "bot":
        return Result(status="skipped", detail="issue author is a bot")

    branch = branch_name(issue.number, issue.title)
    prompt = build_prompt(
        number=issue.number,
        title=issue.title,
        body=issue.body,
        branch=branch,
    )
    base_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _start_branch(repo, branch)
    _ensure_identity(repo)

    with tempfile.TemporaryDirectory(prefix="issue-agent-") as tmp:
        prompt_file = Path(tmp) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        resolved = [part.replace(_PROMPT_FILE_TOKEN, str(prompt_file)) for part in command]
        try:
            completed = subprocess.run(
                resolved,
                input=prompt,
                text=True,
                cwd=repo,
                check=False,
            )
        except FileNotFoundError:
            program = resolved[0]
            publisher.comment(
                issue.number,
                f"The coding agent command `{program}` was not found, so no pull request was opened.",
            )
            return Result(
                status="agent_failed",
                branch=branch,
                detail=f"command not found: {program}",
            )

    if completed.returncode != 0:
        publisher.comment(
            issue.number,
            f"The coding agent failed (exit {completed.returncode}) before a pull request could be opened.",
        )
        return Result(
            status="agent_failed",
            branch=branch,
            detail=f"exit {completed.returncode}",
        )

    _commit_worktree(repo, issue)
    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    if head_sha == base_sha:
        publisher.comment(
            issue.number,
            "No code changes were required, so no pull request was opened.",
        )
        return Result(status="no_changes", branch=branch)

    url = publisher.publish(
        repo=repo,
        branch=branch,
        base_ref=base_ref,
        title=pr_title(issue.number, issue.title),
        body=pr_body(
            issue.number,
            f"Implemented issue #{issue.number}: {issue.title.strip()}",
        ),
        issue_number=issue.number,
    )
    return Result(status="opened", branch=branch, pr_url=url)


def _start_branch(repo: Path, branch: str) -> None:
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
    )
    if existing.returncode == 0:
        _git(repo, "checkout", branch)
        return
    _git(repo, "checkout", "-b", branch)


def _commit_worktree(repo: Path, issue: Issue) -> None:
    status = _git(repo, "status", "--porcelain").stdout
    if not status.strip():
        return
    _git(repo, "add", "-A")
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo,
        check=False,
    )
    if staged.returncode == 0:
        return
    _git(
        repo,
        "commit",
        "-m",
        f"Implement #{issue.number}: {issue.title.strip()}",
    )


def _ensure_identity(repo: Path) -> None:
    name = subprocess.run(
        ["git", "config", "--local", "--get", "user.name"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if name.returncode == 0 and name.stdout.strip():
        return
    _git(repo, "config", "--local", "user.name", "github-actions[bot]")
    _git(repo, "config", "--local", "user.email", _BOT_EMAIL)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed


