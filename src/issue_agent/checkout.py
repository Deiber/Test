"""Find the git checkout the command was started in."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REMOTE = re.compile(
    r"(?:git@github\.com:|https?://github\.com/|ssh://git@github\.com/)"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$"
)


def git_root(start: Path) -> Path:
    """Return the repository root that contains `start`."""
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"Run this command inside a git repository. {detail}".strip())
    return Path(completed.stdout.strip())


def github_slug(repo_dir: Path, remote: str = "origin") -> str:
    """Read `owner/name` from the checkout's GitHub remote."""
    completed = subprocess.run(
        ["git", "remote", "get-url", remote],
        cwd=repo_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"This checkout has no {remote} remote. Pass the repository as owner/name."
        )
    return parse_github_remote(completed.stdout.strip())


def parse_github_remote(url: str) -> str:
    match = _REMOTE.search(url.strip())
    if match is None:
        raise RuntimeError(f"Cannot read a GitHub repository from remote {url!r}.")
    return f"{match.group('owner')}/{match.group('repo')}"
