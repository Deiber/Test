"""Read GitHub issues without adding a third-party HTTP library."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from issue_agent.issues import Issue, IssueRef

Fetch = Callable[[str, str], tuple[bytes, Mapping[str, str]]]

_API = "https://api.github.com"
_PAGE_LIMIT = 10


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GitHubIssues:
    def __init__(self, token: str, *, fetch: Fetch | None = None, api_url: str = _API) -> None:
        if not token.strip():
            raise GitHubError("A GitHub token is required to read issues.")
        self._token = token.strip()
        self._fetch = fetch or _fetch
        self._api_url = api_url.rstrip("/")

    def get(self, ref: IssueRef) -> Issue:
        payload = self._get_json(f"{self._api_url}/repos/{ref.owner}/{ref.repo}/issues/{ref.number}")
        if not isinstance(payload, dict):
            raise GitHubError(f"Unexpected response for {ref.url}")
        return issue_from_payload(payload, ref.slug)

    def list_open(self, repo: str, label: str) -> list[Issue]:
        owner, name = _split_repo(repo)
        quoted = urllib.parse.quote(label, safe="")
        url: str | None = (
            f"{self._api_url}/repos/{owner}/{name}/issues?state=open&labels={quoted}&per_page=100"
        )
        found: list[Issue] = []
        pages = 0
        while url is not None:
            pages += 1
            if pages > _PAGE_LIMIT:
                break
            payload, headers = self._get(url)
            if not isinstance(payload, list):
                raise GitHubError(f"Unexpected issue list for {repo}")
            slug = f"{owner}/{name}"
            found.extend(
                issue_from_payload(item, slug) for item in payload if isinstance(item, dict)
            )
            url = _next_link(headers.get("Link", ""))
        return found

    def _get_json(self, url: str) -> Any:
        payload, _headers = self._get(url)
        return payload

    def _get(self, url: str) -> tuple[Any, Mapping[str, str]]:
        try:
            body, headers = self._fetch(url, self._token)
        except GitHubError:
            raise
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            message = _error_message(detail) or err.reason
            raise GitHubError(f"GitHub API {err.code}: {message}", status=err.code) from err
        except urllib.error.URLError as err:
            raise GitHubError(f"GitHub API request failed: {err.reason}") from err
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as err:
            raise GitHubError("GitHub API returned invalid JSON") from err
        return payload, headers


def issue_from_payload(payload: Mapping[str, Any], repo: str) -> Issue:
    labels = payload.get("labels") or []
    names: list[str] = []
    if isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict) and isinstance(label.get("name"), str):
                names.append(label["name"])
            elif isinstance(label, str):
                names.append(label)
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    author_type = user.get("type") if isinstance(user, dict) else None
    number = payload.get("number")
    title = payload.get("title")
    if not isinstance(number, int) or not isinstance(title, str) or not title.strip():
        raise GitHubError(f"Issue payload for {repo} is missing a number or title")
    body = payload.get("body")
    return Issue(
        number=number,
        title=title.strip(),
        body=body if isinstance(body, str) else "",
        author_type=author_type if isinstance(author_type, str) and author_type else "User",
        labels=tuple(names),
        repo=repo,
        is_pull_request="pull_request" in payload,
    )


def _split_repo(repo: str) -> tuple[str, str]:
    owner, separator, name = repo.strip().partition("/")
    if not separator or not owner or not name or "/" in name:
        raise GitHubError(f"Expected owner/name, got {repo!r}")
    return owner, name


def _next_link(header: str) -> str | None:
    for part in header.split(","):
        if 'rel="next"' not in part:
            continue
        url = part.split(";", 1)[0].strip()
        if url.startswith("<") and url.endswith(">"):
            return url[1:-1]
    return None


def _error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return body.strip()


def _fetch(url: str, token: str) -> tuple[bytes, Mapping[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "issue-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read(), dict(response.headers)
    except urllib.error.HTTPError:
        raise
