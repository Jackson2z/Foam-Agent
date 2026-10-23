"""Parallel tool dispatch for Foam-Agent.

Groups tool calls into read-only (safe to parallelize) and write operations
(serial execution required). Inspired by NullFlux CFDriver's parallel dispatch
pattern (server.deobfuscated.js:52539).
"""

import asyncio
import time
from typing import Any, Callable, Coroutine, Optional

# Read-only tools: safe to run concurrently
READ_ONLY_TOOLS = frozenset({
    "plan",
    "review",
    "visualization",
})

# Write tools: must run serially
WRITE_TOOLS = frozenset({
    "input_writer",
    "run",
    "apply_fixes",
})

MAX_CONCURRENT = 4


def classify_tool(name: str) -> str:
    """Classify a tool as 'read' or 'write'."""
    if name in READ_ONLY_TOOLS:
        return "read"
    if name in WRITE_TOOLS:
        return "write"
    # Default to write for safety
    return "write"


ToolCall = dict  # {"id": str, "name": str, "args": dict}
ToolExecutor = Callable[[str, dict], Coroutine[Any, Any, Any]]
ProgressReporter = Callable[[str], Coroutine[Any, Any, None]]


async def dispatch_tools(
    tool_calls: list[ToolCall],
    executor: ToolExecutor,
    progress: Optional[ProgressReporter] = None,
) -> list[dict]:
    """Execute tool calls with parallel read-only grouping.

    Groups consecutive read-only tool_calls and runs them via asyncio.gather.
    Write operations run serially.

    Args:
        tool_calls: List of {id, name, args} dicts.
        executor: Async function(tool_name, args) -> result.
        progress: Optional async callback for progress messages.

    Returns:
        List of {id, name, result, error} dicts.
    """
    results: list[dict] = []

    # Group consecutive read-only calls for parallel execution
    i = 0
    while i < len(tool_calls):
        # Find the span of consecutive read-only tools
        j = i
        while j < len(tool_calls) and classify_tool(tool_calls[j]["name"]) == "read":
            j += 1

        read_batch = tool_calls[i:j]

        if len(read_batch) >= 2:
            # Parallel execution of read-only batch
            if progress:
                await progress(f"[Parallel] 并行执行 {len(read_batch)} 个只读工具")

            batch_results = await _run_parallel(read_batch, executor)
            results.extend(batch_results)
            i = j
            continue

        # Single tool (either read or write) — execute serially
        tc = tool_calls[i]
        result = await _execute_one(tc, executor)
        results.append(result)
        i += 1

    return results


async def _run_parallel(
    batch: list[ToolCall],
    executor: ToolExecutor,
) -> list[dict]:
    """Run a batch of read-only tools concurrently with semaphore."""
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    results = [None] * len(batch)

    async def _worker(idx: int, tc: ToolCall) -> None:
        async with sem:
            results[idx] = await _execute_one(tc, executor)

    await asyncio.gather(*[_worker(i, tc) for i, tc in enumerate(batch)])
    return results


async def _execute_one(tc: ToolCall, executor: ToolExecutor) -> dict:
    """Execute a single tool call, catching exceptions."""
    try:
        result = await executor(tc["name"], tc["args"])
        return {"id": tc["id"], "name": tc["name"], "result": result, "error": None}
    except Exception as e:
        return {"id": tc["id"], "name": tc["name"], "result": None, "error": str(e)}
