"""Run the task prompt with a local Cursor agent against the current checkout.

The parent workflow still creates the branch, commits leftover edits, and opens the pull request.
Install with `pip install 'issue-agent[cursor]'`.

The sync client cannot start its bridge on Windows, so this adapter uses the async client.
"""

from __future__ import annotations

import asyncio
import os
import sys


def main() -> int:
    try:
        from cursor_sdk import (
            AgentOptions,
            AsyncAgent,
            AsyncClient,
            CursorAgentError,
            LocalAgentOptions,
        )
    except ImportError:
        print(
            "cursor-sdk is not installed. Install the cursor extra: pip install 'issue-agent[cursor]'",
            file=sys.stderr,
        )
        return 1

    if sys.version_info < (3, 12):
        major, minor = sys.version_info[:2]
        print(
            "The Cursor adapter requires Python 3.12 or newer. "
            f"This interpreter is Python {major}.{minor}.",
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

    return asyncio.run(
        _prompt(
            prompt,
            api_key,
            AgentOptions=AgentOptions,
            AsyncAgent=AsyncAgent,
            AsyncClient=AsyncClient,
            CursorAgentError=CursorAgentError,
            LocalAgentOptions=LocalAgentOptions,
        )
    )


async def _prompt(
    prompt: str,
    api_key: str,
    *,
    AgentOptions: type,
    AsyncAgent: type,
    AsyncClient: type,
    CursorAgentError: type,
    LocalAgentOptions: type,
) -> int:
    cwd = os.getcwd()
    try:
        async with await AsyncClient.launch_bridge(workspace=cwd) as client:
            result = await AsyncAgent.prompt(
                prompt,
                AgentOptions(
                    api_key=api_key,
                    model=os.environ.get("CURSOR_MODEL", "composer-2.5"),
                    local=LocalAgentOptions(cwd=cwd),
                ),
                client=client,
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
