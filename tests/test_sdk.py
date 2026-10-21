from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from issue_agent.__main__ import main
from issue_agent.checkout import git_root, parse_github_remote
from issue_agent.github import GitHubIssues
from issue_agent.issues import Issue, IssueRef, parse_issue
from issue_agent.sdk import READY_LABEL, IssueCoding


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[int] = []
        self.comments: list[str] = []

    def publish(self, *, issue_number: int, body: str, **kwargs: object) -> str:
        self.published.append(issue_number)
        assert body.startswith(f"Fixes #{issue_number}\n")
        url = f"https://example.test/pull/{issue_number}"
        self.comment(issue_number, f"Opened {url} for this issue.")
        return url

    def comment(self, issue_number: int, body: str) -> None:
        self.comments.append(body)


class FakeGitHub:
    def __init__(self, issues: dict[int, Issue]) -> None:
        self.issues = issues
        self.gets: list[IssueRef] = []

    def get(self, ref: IssueRef) -> Issue:
        self.gets.append(ref)
        return self.issues[ref.number]

    def list_open(self, repo: str, label: str) -> list[Issue]:
        return [
            issue
            for issue in self.issues.values()
            if issue.repo == repo and label.casefold() in {name.casefold() for name in issue.labels}
        ]


def test_ready_label_default() -> None:
    assert READY_LABEL == "ai-coding-ready"


def test_parse_issue_accepts_url_short_form_and_number() -> None:
    url = parse_issue("https://github.com/Acme/App/issues/12#issuecomment-9")
    assert url == IssueRef(owner="Acme", repo="App", number=12)
    assert parse_issue("acme/app#4").number == 4
    assert parse_issue("#4", default_repo="acme/app").slug == "acme/app"


def test_parse_issue_rejects_unknown_text() -> None:
    with pytest.raises(ValueError):
        parse_issue("not an issue")


def test_work_skips_an_issue_without_the_label(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    github = FakeGitHub(
        {
            12: Issue(
                number=12,
                title="Add ping",
                body="Expose /ping",
                labels=("bug",),
                repo="acme/app",
            )
        }
    )
    coding = IssueCoding(
        [sys.executable, "-c", "raise SystemExit(9)"],
        repo="acme/app",
        repo_dir=repo,
        github=github,
        publisher=RecordingPublisher(),
    )
    result = coding.work("https://github.com/acme/app/issues/12")
    assert result.status == "skipped"
    assert result.detail == "missing label ai-coding-ready"
    assert github.gets[0].number == 12
    assert _branches(repo) == ["main"]


def test_work_runs_when_the_label_matches_any_case(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    github = FakeGitHub({3: _ready_issue(3, "Add ping", labels=("AI-Coding-Ready",))})
    publisher = RecordingPublisher()
    coding = IssueCoding(
        [sys.executable, "-c", "from pathlib import Path; Path('ping.py').write_text('ok\\n')"],
        repo="acme/app",
        repo_dir=repo,
        github=github,
        publisher=publisher,
    )
    result = coding.work("acme/app#3")
    assert result.status == "opened"
    assert result.branch == "issue/3-add-ping"
    assert publisher.published == [3]
    assert (repo / "ping.py").read_text(encoding="utf-8") == "ok\n"


def test_work_open_issues_keeps_each_change_on_its_own_branch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "text = sys.stdin.read()\n"
        "number = text.split('issue #', 1)[1].split()[0]\n"
        "Path(f'done-{number}.txt').write_text('ok\\n')\n",
        encoding="utf-8",
    )
    github = FakeGitHub(
        {
            2: _ready_issue(2, "Second"),
            1: _ready_issue(1, "First"),
            9: Issue(number=9, title="Pull", body="", labels=(READY_LABEL,), repo="acme/app", is_pull_request=True),
        }
    )
    coding = IssueCoding(
        [sys.executable, str(script)],
        repo="acme/app",
        repo_dir=repo,
        github=github,
        publisher=RecordingPublisher(),
    )
    results = coding.work_open_issues()
    assert [result.status for result in results] == ["opened", "opened", "skipped"]
    assert _file_on_branch(repo, "issue/1-first", "done-1.txt") == "ok\n"
    assert _file_on_branch(repo, "issue/1-first", "done-2.txt") is None
    assert _file_on_branch(repo, "issue/2-second", "done-2.txt") == "ok\n"
    assert _file_on_branch(repo, "issue/2-second", "done-1.txt") is None


def test_parse_github_remote() -> None:
    assert parse_github_remote("https://github.com/Deiber/Test.git") == "Deiber/Test"
    assert parse_github_remote("git@github.com:acme/app.git") == "acme/app"
    assert parse_github_remote("ssh://git@github.com/acme/my.repo") == "acme/my.repo"


def test_command_uses_the_checkout_root_and_origin(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    nested = repo / "pkg"
    nested.mkdir()
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/app.git"],
        cwd=repo,
        check=True,
    )
    github = FakeGitHub({3: _ready_issue(3, "Add ping")})
    coding = IssueCoding(
        [sys.executable, "-c", "from pathlib import Path; Path('ping.py').write_text('ok\\n')"],
        repo_dir=nested,
        github=github,
        publisher=RecordingPublisher(),
    )
    result = coding.work("#3")
    assert coding.repo == "acme/app"
    assert coding.repo_dir == git_root(nested)
    assert result.status == "opened"
    assert (repo / "ping.py").read_text(encoding="utf-8") == "ok\n"


def test_action_mode_skips_without_the_label(tmp_path: Path) -> None:
    code = main(
        [],
        env={
            "ISSUE_NUMBER": "4",
            "ISSUE_TITLE": "Add ping",
            "ISSUE_LABELS": "bug",
            "REPO": "acme/app",
            "REPO_DIR": str(tmp_path),
            "AGENT_COMMAND": f"{sys.executable} -c \"raise SystemExit(9)\"",
        },
    )
    assert code == 0


def test_github_client_reads_one_issue_and_follows_the_next_page() -> None:
    calls: list[str] = []

    def fetch(url: str, token: str) -> tuple[bytes, dict[str, str]]:
        assert token == "token"
        calls.append(url)
        if url.rstrip("/").endswith("/issues/5"):
            payload = {
                "number": 5,
                "title": "Now",
                "body": None,
                "labels": [{"name": READY_LABEL}],
                "user": {"type": "User"},
            }
            return json.dumps(payload).encode(), {}
        if "page=2" in url:
            payload = [
                {
                    "number": 8,
                    "title": "Later",
                    "body": "",
                    "labels": [{"name": READY_LABEL}],
                    "user": {"type": "User"},
                }
            ]
            return json.dumps(payload).encode(), {}
        payload = [
            {
                "number": 5,
                "title": "Now",
                "body": "",
                "labels": [{"name": READY_LABEL}],
                "user": {"type": "User"},
            }
        ]
        headers = {"Link": '<https://api.github.com/repos/acme/app/issues?page=2>; rel="next"'}
        return json.dumps(payload).encode(), headers

    client = GitHubIssues("token", fetch=fetch, api_url="https://api.github.com")
    issue = client.get(IssueRef(owner="acme", repo="app", number=5))
    assert issue.title == "Now"
    assert issue.body == ""
    assert issue.labels == (READY_LABEL,)

    listed = client.list_open("acme/app", READY_LABEL)
    assert [item.number for item in listed] == [5, 8]
    assert any("labels=ai-coding-ready" in url for url in calls)


def _ready_issue(number: int, title: str, labels: tuple[str, ...] = (READY_LABEL,)) -> Issue:
    return Issue(number=number, title=title, body="Do the work", labels=labels, repo="acme/app")


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "dev@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dev"], cwd=repo, check=True)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, check=True, capture_output=True)
    return repo


def _branches(repo: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


def _file_on_branch(repo: Path, branch: str, name: str) -> str | None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{branch}:{name}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    shown = subprocess.run(
        ["git", "show", f"{branch}:{name}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return shown.stdout
