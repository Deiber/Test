"""Run the task prompt with a local Cursor agent against the current checkout.

The parent workflow still creates the branch, commits leftover edits, and opens the pull request.
Install with `pip install 'issue-agent[cursor]'`.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions
    except ImportError:
        print(
            "cursor-sdk is not installed. Install the cursor extra: pip install 'issue-agent[cursor]'",
            file=sys.stderr,
        )
        return 1

    prompt = sys.stdin.read()
    if not prompt.strip():
        print("The task prompt was empty.", file=sys.stderr)
        return 1

    api_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not api_key:
        print("CURSOR_API_KEY is required for the Cursor adapter.", file=sys.stderr)
        return 1

    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=os.environ.get("CURSOR_MODEL", "composer-2.5"),
                local=LocalAgentOptions(cwd=os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        print(
            f"startup failed: {err.message} request_id={err.request_id} retryable={err.is_retryable}",
            file=sys.stderr,
        )
        return 1

    print(f"status={result.status} id={getattr(result, 'id', '')}")
    if result.result:
        print(result.result)
    if result.status == "error":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
