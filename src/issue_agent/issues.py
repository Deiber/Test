"""Issue identity shared by the runner and the public kit."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ISSUE_URL = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/issues/(?P<number>\d+)/?$",
    re.IGNORECASE,
)
_ISSUE_SHORT = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
_ISSUE_HASH = re.compile(r"^#(?P<number>\d+)$")


@dataclass(frozen=True)
class IssueRef:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.slug}/issues/{self.number}"


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    author_type: str = "User"
    labels: tuple[str, ...] = ()
    repo: str = ""
    is_pull_request: bool = False


def parse_issue(value: str, *, default_repo: str | None = None) -> IssueRef:
    """Accept a GitHub issue URL, `owner/repo#number`, or `#number` when the repo is known."""
    text = value.strip()
    short = _ISSUE_SHORT.fullmatch(text)
    if short is not None:
        return _ref(short.group("owner"), short.group("repo"), short.group("number"))

    hashed = _ISSUE_HASH.fullmatch(text)
    if hashed is not None:
        if not default_repo:
            raise ValueError("A repository is required when the issue is only a number")
        owner, separator, name = default_repo.strip().partition("/")
        if not separator or not owner or not name:
            raise ValueError(f"Expected owner/name, got {default_repo!r}")
        return _ref(owner, name, hashed.group("number"))

    cleaned = text.split("?", 1)[0].split("#", 1)[0]
    match = _ISSUE_URL.fullmatch(cleaned)
    if match is None:
        raise ValueError(f"Not a GitHub issue URL: {value}")
    return _ref(match.group("owner"), match.group("repo"), match.group("number"))


def has_label(labels: tuple[str, ...] | list[str], required: str) -> bool:
    wanted = required.casefold()
    return any(label.casefold() == wanted for label in labels)


def _ref(owner: str, repo: str, number: str) -> IssueRef:
    return IssueRef(owner=owner, repo=repo, number=int(number))
