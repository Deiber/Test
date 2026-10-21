from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from issue_agent.__main__ import exit_code, issue_from_env, resolve_command
from issue_agent.prompt import branch_name, build_prompt, pr_body, pr_title, slugify
from issue_agent.publish import GitHubPublisher
from issue_agent.runner import Issue, Result, implement, split_command


def test_slug_and_branch_are_stable() -> None:
    assert slugify("Add Health Check!!!") == "add-health-check"
    assert slugify("***") == "task"
    assert branch_name(12, "Add Health Check") == "issue/12-add-health-check"


def test_prompt_keeps_the_agent_on_the_branch() -> None:
    prompt = build_prompt(number=4, title="Add ping", body="Expose /ping", branch="issue/4-add-ping")
    assert "AGENTS.md" in prompt
    assert "issue/4-add-ping" in prompt
    assert "Do not push." in prompt
    assert "Fixes #4" in prompt


def test_pr_body_links_the_issue() -> None:
    assert pr_body(9, "done").startswith("Fixes #9\n")
    assert pr_title(9, "Short").startswith("Implement #9:")


def test_split_command_replaces_prompt_file() -> None:
    prompt_file = Path("/tmp/prompt.md")
    parts = split_command("agent --file {prompt_file}", prompt_file)
    assert parts == ["agent", "--file", str(prompt_file)]


def test_resolve_command_prefers_agent_command() -> None:
    assert resolve_command({"AGENT_COMMAND": "echo hi", "CURSOR_API_KEY": "cursor_x"}) == ["echo", "hi"]


def test_resolve_command_defaults_to_cursor_adapter() -> None:
    assert resolve_command({"CURSOR_API_KEY": "cursor_x"}) == [
        sys.executable,
        "-m",
        "issue_agent.adapters.cursor_local",
    ]


def test_resolve_command_requires_an_agent() -> None:
    with pytest.raises(SystemExit):
        resolve_command({})


def test_issue_from_env_rejects_a_missing_title() -> None:
    with pytest.raises(SystemExit):
        issue_from_env({"ISSUE_NUMBER": "1"})


def test_exit_code_marks_agent_failure() -> None:
    assert exit_code(Result(status="opened")) == 0
    assert exit_code(Result(status="agent_failed")) == 2


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []
        self.comments: list[tuple[int, str]] = []

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
        self.published.append(
            {
                "repo": repo,
                "branch": branch,
                "base_ref": base_ref,
                "title": title,
                "body": body,
                "issue_number": issue_number,
            }
        )
        url = f"https://example.test/pull/{issue_number}"
        self.comment(issue_number, f"Opened {url} for this issue.")
        return url

    def comment(self, issue_number: int, body: str) -> None:
        self.comments.append((issue_number, body))


def test_prompt_file_token_receives_the_issue(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    seen = tmp_path / "seen.txt"
    script = tmp_path / "read_prompt.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "Path(sys.argv[2]).write_text(Path(sys.argv[1]).read_text(encoding='utf-8'), encoding='utf-8')\n",
        encoding="utf-8",
    )
    result = implement(
        repo=repo,
        issue=Issue(number=4, title="Add ping", body="Expose /ping"),
        command=[sys.executable, str(script), "{prompt_file}", str(seen)],
        publisher=RecordingPublisher(),
        base_ref="main",
    )
    assert result.status == "no_changes"
    text = seen.read_text(encoding="utf-8")
    assert "Add ping" in text
    assert "Expose /ping" in text


def test_bot_issues_are_skipped(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    publisher = RecordingPublisher()
    result = implement(
        repo=repo,
        issue=Issue(number=1, title="Ignore", body="", author_type="Bot"),
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "skipped"
    assert publisher.published == []
    assert publisher.comments == []


def test_agent_edits_are_committed_and_published(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    publisher = RecordingPublisher()
    writer = tmp_path / "writer.py"
    writer.write_text("from pathlib import Path\nPath('hello.py').write_text('VALUE = 1\\n')\n", encoding="utf-8")
    result = implement(
        repo=repo,
        issue=Issue(number=7, title="Add hello", body="Write hello.py"),
        command=[sys.executable, str(writer)],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "opened"
    assert result.branch == "issue/7-add-hello"
    assert (repo / "hello.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert publisher.published[0]["body"].startswith("Fixes #7\n")
    assert "Opened" in publisher.comments[0][1]


def test_clean_agent_does_not_publish(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    publisher = RecordingPublisher()
    result = implement(
        repo=repo,
        issue=Issue(number=3, title="Question", body="What is this?"),
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "no_changes"
    assert publisher.published == []
    assert publisher.comments


def test_failed_agent_does_not_publish(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    publisher = RecordingPublisher()
    result = implement(
        repo=repo,
        issue=Issue(number=8, title="Broken", body=""),
        command=[sys.executable, "-c", "raise SystemExit(3)"],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "agent_failed"
    assert publisher.published == []
    assert "exit 3" in publisher.comments[0][1]


def test_missing_agent_command_is_reported(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    publisher = RecordingPublisher()
    result = implement(
        repo=repo,
        issue=Issue(number=1, title="Add hello", body=""),
        command=["codex-is-not-installed", "exec"],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "agent_failed"
    assert result.detail == "command not found: codex-is-not-installed"
    assert publisher.published == []


def test_existing_issue_branch_is_reused(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "issue/4-add-ping"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    publisher = RecordingPublisher()
    result = implement(
        repo=repo,
        issue=Issue(number=4, title="Add ping", body=""),
        command=[sys.executable, "-c", "from pathlib import Path; Path('ping.py').write_text('ok\\n')"],
        publisher=publisher,
        base_ref="main",
    )
    assert result.status == "opened"
    assert result.branch == "issue/4-add-ping"
    assert (repo / "ping.py").read_text(encoding="utf-8") == "ok\n"


def test_comment_uses_the_api_when_gh_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, int, str]] = []

    def fake_post(repo: str, number: int, body: str, token: str | None = None) -> None:
        posted.append((repo, number, body))

    monkeypatch.setattr("issue_agent.publish.post_issue_comment", fake_post)

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[0] == "gh":
            raise FileNotFoundError
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    GitHubPublisher("acme/app", run=run).comment(1, "hello")
    assert posted == [("acme/app", 1, "hello")]


def test_cursor_adapter_requires_python_312(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import types

    module = types.ModuleType("cursor_sdk")
    module.AgentOptions = object
    module.AsyncAgent = object
    module.AsyncClient = object
    module.CursorAgentError = type("CursorAgentError", (Exception,), {})
    module.LocalAgentOptions = object
    monkeypatch.setitem(sys.modules, "cursor_sdk", module)
    monkeypatch.setattr(sys, "version_info", (3, 11, 0, "final", 0))
    from issue_agent.adapters import cursor_local

    assert cursor_local.main() == 1
    assert "Python 3.12" in capsys.readouterr().err


def test_github_publisher_reuses_an_existing_pr() -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout="https://github.com/acme/app/pull/4\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    url = GitHubPublisher("acme/app", run=run).publish(
        repo=Path("."),
        branch="issue/4-ping",
        base_ref="main",
        title="Implement #4: ping",
        body="Fixes #4\n\nImplemented.\n",
        issue_number=4,
    )
    assert url == "https://github.com/acme/app/pull/4"
    assert not any(args[:3] == ["gh", "pr", "create"] for args in calls)
    assert ["gh", "issue", "comment", "4"] == calls[-1][:4]


def test_cursor_adapter_reports_a_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "cursor_sdk":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from issue_agent.adapters import cursor_local

    assert cursor_local.main() == 1


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
