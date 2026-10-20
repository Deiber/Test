"""Vendor-neutral issue prompt, branch name, and pull request body."""

from __future__ import annotations

import re

_SLUG_MAX = 40


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    slug = slug[:_SLUG_MAX].strip("-")
    return slug or "task"


def branch_name(number: int, title: str) -> str:
    return f"issue/{number}-{slugify(title)}"


def build_prompt(*, number: int, title: str, body: str, branch: str) -> str:
    issue_body = body.strip() or "(no description)"
    return f"""Read AGENTS.md and follow it.

Implement GitHub issue #{number} in this repository.

Title: {title}

Body:
{issue_body}

You are already on branch `{branch}`. Stay on this branch.
Do not push. Do not open a pull request.
Leave the implementation in the working tree, or commit it on this branch.
The workflow opens the pull request and includes `Fixes #{number}` so GitHub links it to the issue.
"""


def pr_title(number: int, title: str) -> str:
    text = f"Implement #{number}: {title.strip()}"
    if len(text) <= 72:
        return text
    return text[:71].rstrip() + "…"


def pr_body(number: int, summary: str) -> str:
    text = summary.strip() or "Implemented the requested change."
    return f"Fixes #{number}\n\n{text}\n"
