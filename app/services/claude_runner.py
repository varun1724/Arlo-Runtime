from __future__ import annotations

import asyncio
import json
import logging

from app.core.config import settings

logger = logging.getLogger("arlo.claude_runner")


class ClaudeRunError(Exception):
    """Raised when claude CLI fails."""

    def __init__(self, message: str, stderr: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.exit_code = exit_code


class ClaudeTimeoutError(ClaudeRunError):
    """Raised when claude CLI exceeds the timeout."""


async def run_claude(
    prompt: str,
    *,
    cwd: str | None = None,
    timeout: int | None = None,
    output_format: str = "json",
    allow_permissions: bool = False,
    model: str | None = None,
) -> dict:
    """Run `claude -p` as an async subprocess and return parsed JSON output.

    Args:
        prompt: The prompt to send to Claude Code CLI.
        cwd: Working directory for the subprocess.
        timeout: Max seconds to wait. Defaults to settings.research_timeout_seconds.
        output_format: Output format flag (json, text, stream-json).
        allow_permissions: If True, add --dangerously-skip-permissions so Claude Code
            can write files and run bash without interactive approval. Required for
            builder jobs that need to create files and install dependencies.
        model: Model to use (e.g. "sonnet", "opus"). Overrides config default.

    Returns:
        Parsed JSON dict from Claude Code CLI output.

    Raises:
        ClaudeRunError: If the CLI exits with non-zero or output can't be parsed.
        ClaudeTimeoutError: If the CLI exceeds the timeout.
    """
    if timeout is None:
        timeout = settings.research_timeout_seconds

    cmd = [settings.claude_command, "-p", prompt, "--output-format", output_format]

    if allow_permissions:
        cmd.append("--dangerously-skip-permissions")

    # Model selection: explicit param > config default
    effective_model = model or settings.claude_model
    if effective_model:
        cmd.extend(["--model", effective_model])

    logger.info("Running Claude Code CLI (timeout=%ds, cwd=%s)", timeout, cwd or "(default)")
    logger.debug("Command: %s", " ".join(cmd[:4]) + " ...")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        # Kill the process if it's still running
        try:
            process.kill()
            await process.wait()
        except ProcessLookupError:
            pass
        raise ClaudeTimeoutError(
            f"Claude Code CLI timed out after {timeout}s",
            exit_code=-1,
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if process.returncode != 0:
        logger.error(
            "Claude Code CLI exited with code %d: %s",
            process.returncode,
            stderr[:500],
        )
        raise ClaudeRunError(
            f"Claude Code CLI exited with code {process.returncode}",
            stderr=stderr,
            exit_code=process.returncode,
        )

    # Parse JSON output
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Claude output as JSON: %s", str(e))
        logger.debug("Raw stdout (first 1000 chars): %s", stdout[:1000])
        raise ClaudeRunError(
            f"Failed to parse Claude output as JSON: {e}",
            stderr=stderr,
            exit_code=process.returncode,
        )

    logger.info("Claude Code CLI completed successfully")
    return result
