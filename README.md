# Issue agent

When a GitHub issue labeled `ai-coding-ready` is opened or labeled, this repository runs a coding agent, commits the result on a new branch, and opens a pull request linked to that issue.

The same rule is available as a Python kit. Point it at an issue URL, or ask it to look through open issues. It starts the agent only when that label is present.

The agent is whatever command you configure. `AGENTS.md` is the contract that agent follows. The workflow owns the branch and the pull request, so the same path works for Cursor, Claude, Codex, or any other tool that can edit a checkout.

## What happens

1. Opening an issue, or adding the label `ai-coding-ready`, starts `.github/workflows/issue-agent.yml`. Issues opened by bots are ignored. Issues without that label are ignored.
2. The workflow checks out the default branch and runs `python -m issue_agent`.
3. The runner creates `issue/<number>-<slug>` and starts `AGENT_COMMAND`. The task is on stdin. `{prompt_file}` in the command expands to a file with the same task.
4. If the working tree changed, the runner commits it. If the agent already committed, that commit is kept.
5. The runner pushes the branch and opens a pull request whose body starts with `Fixes #<number>`. GitHub attaches the pull request to the issue and closes the issue when the pull request merges.
6. The issue gets a comment with the pull request URL. If the agent makes no edits, the comment says that no pull request was opened.

## Configure the agent

In the GitHub repository, add a variable named `AGENT_COMMAND`.

The command has to edit the checkout and then exit. Two forms work:

```text
# task is written to stdin
my-agent --headless

# task is also available as a file
my-agent --prompt-file {prompt_file}
```

Pass that tool's API key as an Actions secret, and add the secret name to the `env` block of `.github/workflows/issue-agent.yml` if it is not already there. `CURSOR_API_KEY`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY` are already forwarded.

If `AGENT_COMMAND` is empty and `CURSOR_API_KEY` is set, the run uses the local Cursor adapter:

```text
python -m issue_agent.adapters.cursor_local
```

Install that extra before using it. In the workflow install step, use:

```bash
pip install ".[cursor]"
```

The adapter reads `CURSOR_MODEL` (default `composer-2.5`). Create the key at [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) and store it as the `CURSOR_API_KEY` secret. The workflow still creates the branch and the pull request; the adapter only edits the checkout.

## Python kit

```python
from issue_agent import IssueCoding

coding = IssueCoding(
    "codex exec --sandbox workspace-write -",
    repo="owner/name",
)
coding.work("https://github.com/owner/name/issues/12")
coding.work_open_issues()
```

`work` fetches that issue and returns without editing when the label is missing. `work_open_issues` lists open issues that already have the label and works through them in order. The label name defaults to `ai-coding-ready`. Pass `label=` to use another one.

The checkout in `repo_dir` (the current directory by default) must be that repository. Reading issues uses `GITHUB_TOKEN` or `GH_TOKEN`.

From the command line:

```bash
issue-agent work https://github.com/owner/name/issues/12 --repo owner/name --command "codex exec --sandbox workspace-write -"
issue-agent work-open --repo owner/name --command "codex exec --sandbox workspace-write -"
```

## Local check

```bash
pip install ".[dev]"
pytest
```
