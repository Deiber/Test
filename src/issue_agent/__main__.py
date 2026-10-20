"""Entry point used by the GitHub Action and by `python -m issue_agent`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from issue_agent.github import GitHubError
from issue_agent.issues import Issue
from issue_agent.publish import GitHubPublisher
from issue_agent.runner import Result, parse_command
from issue_agent.sdk import READY_LABEL, IssueCoding

_MISSING_COMMAND = (
    "Set AGENT_COMMAND to the coding agent to run. "
    "The task is passed on stdin. Use {prompt_file} in the command when the agent reads a file path. "
    "With CURSOR_API_KEY set and AGENT_COMMAND empty, the Cursor local adapter is used."
)


def issue_from_env(env: Mapping[str, str]) -> Issue:
    number = (env.get("ISSUE_NUMBER") or "").strip()
    title = (env.get("ISSUE_TITLE") or "").strip()
    if not number.isdigit() or not title:
        raise SystemExit("ISSUE_NUMBER and ISSUE_TITLE are required")
    raw_labels = env.get("ISSUE_LABELS") or ""
    labels = tuple(part.strip() for part in raw_labels.split(",") if part.strip())
    return Issue(
        number=int(number),
        title=title,
        body=env.get("ISSUE_BODY") or "",
        author_type=(env.get("ISSUE_AUTHOR_TYPE") or "User").strip() or "User",
        labels=labels,
        repo=(env.get("REPO") or "").strip(),
    )


def resolve_command(env: Mapping[str, str]) -> list[str]:
    command = (env.get("AGENT_COMMAND") or "").strip()
    if command:
        return parse_command(command)
    if (env.get("CURSOR_API_KEY") or "").strip():
        return [sys.executable, "-m", "issue_agent.adapters.cursor_local"]
    raise SystemExit(_MISSING_COMMAND)


def exit_code(result: Result) -> int:
    if result.status == "agent_failed":
        return 2
    return 0


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    environ = os.environ if env is None else env
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _run_action(environ)
    return _run_cli(args, environ)


def _run_action(environ: Mapping[str, str]) -> int:
    issue = issue_from_env(environ)
    repo_slug = (environ.get("REPO") or "").strip()
    if not repo_slug:
        raise SystemExit("REPO is required (owner/name)")
    label = (environ.get("READY_LABEL") or READY_LABEL).strip() or READY_LABEL
    coding = IssueCoding(
        resolve_command(environ),
        repo=repo_slug,
        repo_dir=Path(environ.get("REPO_DIR") or os.getcwd()),
        label=label,
        base_ref=(environ.get("BASE_REF") or "main").strip() or "main",
        publisher=GitHubPublisher(repo_slug),
    )
    return _emit(coding.work_issue(issue))


def _run_cli(argv: Sequence[str], environ: Mapping[str, str]) -> int:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repo", default="")
    shared.add_argument("--repo-dir", default="")
    shared.add_argument("--label", default=environ.get("READY_LABEL") or READY_LABEL)
    shared.add_argument("--base", default=environ.get("BASE_REF") or "main")
    shared.add_argument("--command", default=environ.get("AGENT_COMMAND") or "")
    shared.add_argument("--token", default="")

    parser = argparse.ArgumentParser(prog="issue-agent")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    work = subparsers.add_parser("work", parents=[shared], help="Work one issue URL if it has the ready label")
    work.add_argument("issue")

    subparsers.add_parser(
        "work-open",
        parents=[shared],
        help="Work every open issue that has the ready label",
    )

    parsed = parser.parse_args(list(argv))
    command = parse_command(parsed.command) if parsed.command else resolve_command(environ)
    coding = IssueCoding(
        command,
        repo=parsed.repo or None,
        repo_dir=parsed.repo_dir or Path.cwd(),
        label=parsed.label,
        base_ref=parsed.base,
        token=parsed.token or None,
    )
    if parsed.command_name == "work":
        return _emit(coding.work(parsed.issue))
    results = coding.work_open_issues()
    codes = [_emit(result) for result in results]
    return 2 if 2 in codes else 0


def _emit(result: Result) -> int:
    print(f"status={result.status} branch={result.branch} pr={result.pr_url or ''}")
    if result.detail:
        print(result.detail, file=sys.stderr)
    return exit_code(result)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, GitHubError) as err:
        print(str(err), file=sys.stderr)
        raise SystemExit(1) from err
