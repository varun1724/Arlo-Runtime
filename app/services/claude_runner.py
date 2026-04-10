from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("arlo.claude_runner")


# Round 3: Per-million-token prices for cost estimation. These are
# approximate and intentionally conservative — they're for visibility, not
# billing. Update as Anthropic publishes new pricing.
# (input_per_mtok_usd, output_per_mtok_usd)
_MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "haiku": (0.80, 4.00),
    "sonnet": (3.00, 15.00),
    "opus": (15.00, 75.00),
}
_DEFAULT_PRICE = (3.00, 15.00)  # assume sonnet if model is unknown


def extract_usage(claude_output: dict[str, Any]) -> dict[str, int | float | None]:
    """Pull token usage and estimated cost from a Claude CLI JSON result.

    The Claude Code CLI's ``--output-format json`` response includes a
    ``usage`` block with ``input_tokens``, ``output_tokens``, and (sometimes)
    cache-related counters. This helper normalizes them and computes a
    rough USD cost based on the per-model price table above.

    Returns a dict with keys ``input_tokens``, ``output_tokens``,
    ``estimated_cost_usd``. Any field can be ``None`` if the CLI response
    didn't include usage data (e.g. older Claude Code versions).
    """
    usage = claude_output.get("usage") if isinstance(claude_output, dict) else None
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None, "estimated_cost_usd": None}

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")

    # Some Claude CLI versions report cache hits separately. Count them as input.
    cache_creation = usage.get("cache_creation_input_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0
    if isinstance(input_tokens, int):
        input_tokens = input_tokens + cache_creation + cache_read

    cost: float | None = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        # Try to identify the model from the result; fall back to default.
        model_key = _DEFAULT_PRICE
        model_field = (
            claude_output.get("model")
            if isinstance(claude_output, dict) else None
        )
        if isinstance(model_field, str):
            for key, price in _MODEL_PRICES_USD_PER_MTOK.items():
                if key in model_field.lower():
                    model_key = price
                    break
        in_price, out_price = model_key
        cost = round(
            (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price,
            6,
        )

    return {
        "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
        "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
        "estimated_cost_usd": cost,
    }


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
