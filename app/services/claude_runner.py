from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings

logger = logging.getLogger("arlo.claude_runner")

# Round 4: type alias for the optional streaming progress callback.
# Receives a snapshot dict with at least 'accumulated_chars' and 'usage'
# (which may itself be None until the first usage event arrives).
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


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


def _safe_int(value) -> int | None:
    """Coerce a usage value to int, tolerating CLI versions that emit strings.

    Round 4 bug fix: previously ``usage.get("cache_creation_input_tokens")
    or 0`` would preserve a string ``"100"`` and then crash on
    ``int + str`` arithmetic. This helper normalizes everything to int
    or None up front.
    """
    if isinstance(value, bool):
        # bool is a subclass of int — treat as not-an-int for our purposes
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


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

    # Round 4: defensively coerce all token counts via _safe_int. This
    # tolerates Claude CLI versions that emit strings instead of ints.
    input_tokens = _safe_int(usage.get("input_tokens"))
    output_tokens = _safe_int(usage.get("output_tokens"))

    # Some Claude CLI versions report cache hits separately. Count them as input.
    cache_creation = _safe_int(usage.get("cache_creation_input_tokens")) or 0
    cache_read = _safe_int(usage.get("cache_read_input_tokens")) or 0
    if input_tokens is not None:
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

    # input_tokens and output_tokens are already int-or-None thanks to
    # _safe_int above; the explicit isinstance was leftover from before.
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
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
    output_format: str = "stream-json",
    allow_permissions: bool = False,
    model: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Run `claude -p` as an async subprocess and return parsed JSON output.

    Round 4: defaults to ``stream-json`` so callers can pass an
    ``on_progress`` callback and observe accumulated content + usage
    snapshots in real time. The legacy single-blob ``json`` format is
    still supported for callers that explicitly opt in.

    Args:
        prompt: The prompt to send to Claude Code CLI.
        cwd: Working directory for the subprocess.
        timeout: Max seconds to wait. Defaults to settings.research_timeout_seconds.
        output_format: Output format flag. ``stream-json`` (default) parses
            line-by-line and supports ``on_progress``. ``json`` and ``text``
            buffer everything until the process exits.
        allow_permissions: If True, add --dangerously-skip-permissions so Claude Code
            can write files and run bash without interactive approval. Required for
            builder jobs that need to create files and install dependencies.
        model: Model to use (e.g. "sonnet", "opus"). Overrides config default.
        on_progress: Optional async callback. Invoked after each parsed
            stream-json event with a snapshot dict ``{accumulated_chars,
            usage}``. Only used when ``output_format='stream-json'``.

    Returns:
        Dict with the same shape regardless of output_format:
        ``{"result": <text>, "usage": <dict|None>, "model": <str|None>}``

    Raises:
        ClaudeRunError: If the CLI exits with non-zero or output can't be parsed.
        ClaudeTimeoutError: If the CLI exceeds the timeout.
    """
    if timeout is None:
        timeout = settings.research_timeout_seconds

    cmd = [settings.claude_command, "-p", prompt, "--output-format", output_format]

    # stream-json requires --verbose to actually emit events
    if output_format == "stream-json":
        cmd.append("--verbose")

    if allow_permissions:
        cmd.append("--dangerously-skip-permissions")

    # Model selection: explicit param > config default
    effective_model = model or settings.claude_model
    if effective_model:
        cmd.extend(["--model", effective_model])

    logger.info(
        "Running Claude Code CLI (format=%s, timeout=%ds, cwd=%s)",
        output_format, timeout, cwd or "(default)",
    )
    logger.debug("Command: %s", " ".join(cmd[:4]) + " ...")

    if output_format == "stream-json":
        return await _run_claude_streaming(cmd, cwd=cwd, timeout=timeout, on_progress=on_progress)
    return await _run_claude_buffered(cmd, cwd=cwd, timeout=timeout)


async def _run_claude_buffered(
    cmd: list[str],
    *,
    cwd: str | None,
    timeout: int,
) -> dict:
    """Legacy single-blob path. Used when output_format != 'stream-json'."""
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
            process.returncode, stderr[:500],
        )
        raise ClaudeRunError(
            f"Claude Code CLI exited with code {process.returncode}",
            stderr=stderr,
            exit_code=process.returncode,
        )

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

    logger.info("Claude Code CLI completed successfully (buffered)")
    return result


async def _run_claude_streaming(
    cmd: list[str],
    *,
    cwd: str | None,
    timeout: int,
    on_progress: ProgressCallback | None,
) -> dict:
    """Stream-json path. Reads stdout line-by-line, parses each as a JSON
    event, accumulates text content, and yields snapshots to on_progress.

    Returns the same dict shape as ``_run_claude_buffered`` so callers
    don't need to know which path was used.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except (OSError, FileNotFoundError) as e:
        raise ClaudeRunError(f"Failed to start Claude CLI: {e}") from e

    accumulated_text_parts: list[str] = []
    latest_usage: dict[str, Any] | None = None
    latest_model: str | None = None
    latest_tool_activity: str | None = None  # Round 5: e.g. "Using WebSearch"
    final_result_event: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout

    # Round 5.5 hotfix: do NOT use process.stdout.readline() — its
    # underlying StreamReader has a hardcoded 64KB per-line limit and
    # raises LimitOverrunError when Claude emits a single stream-json
    # event larger than that. Deep research mode triggers this regularly
    # because individual assistant content blocks can hit hundreds of KB.
    # Instead, read raw bytes in chunks and split on '\n' ourselves —
    # no per-line size cap, just whatever memory the process has.
    line_buffer = bytearray()

    async def _read_next_line() -> bytes | None:
        """Return the next complete line (without trailing \\n), or
        None on EOF. No size limit. Respects the outer ``deadline``.
        """
        while True:
            nl_idx = line_buffer.find(b"\n")
            if nl_idx != -1:
                line = bytes(line_buffer[:nl_idx])
                del line_buffer[:nl_idx + 1]
                return line

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process(process)
                raise ClaudeTimeoutError(
                    f"Claude Code CLI timed out after {timeout}s",
                    exit_code=-1,
                )
            try:
                chunk = await asyncio.wait_for(
                    process.stdout.read(65536), timeout=remaining
                )
            except asyncio.TimeoutError:
                _kill_process(process)
                raise ClaudeTimeoutError(
                    f"Claude Code CLI timed out after {timeout}s",
                    exit_code=-1,
                )
            if not chunk:
                # EOF — flush any trailing partial line then signal end
                if line_buffer:
                    line = bytes(line_buffer)
                    line_buffer.clear()
                    return line
                return None
            line_buffer.extend(chunk)

    try:
        while True:
            line_bytes = await _read_next_line()
            if line_bytes is None:
                # EOF — process is exiting
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # Malformed line — log and skip; don't crash the run
                logger.debug("stream-json: skipping unparseable line (%d chars)", len(line))
                continue

            if not isinstance(event, dict):
                continue

            event_type = event.get("type")

            # Capture model from any event that has it (system init typically)
            if isinstance(event.get("model"), str):
                latest_model = event["model"]
            # Some Claude versions emit model nested in message
            msg = event.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("model"), str):
                latest_model = msg["model"]

            # Accumulate assistant text content
            if event_type == "assistant" and isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "text":
                            text = block.get("text")
                            if isinstance(text, str):
                                accumulated_text_parts.append(text)
                        elif block_type == "tool_use":
                            # Round 5: surface tool activity in progress
                            # messages. Claude's assistant events can
                            # include tool_use blocks inline (alongside
                            # text) for WebSearch, Read, etc.
                            tool_name = block.get("name") or "tool"
                            latest_tool_activity = f"Using {tool_name}"

            # Round 5: top-level tool_use/tool_result events (some CLI
            # versions emit them as separate events rather than blocks)
            if event_type == "tool_use":
                tool_name = (
                    event.get("name")
                    or (msg or {}).get("name")
                    or "tool"
                )
                latest_tool_activity = f"Using {tool_name}"
            elif event_type == "tool_result":
                # Back to text generation; clear the tool activity marker
                latest_tool_activity = None

            # The final 'result' event has the canonical full result + usage
            if event_type == "result":
                final_result_event = event
                usage = event.get("usage")
                if isinstance(usage, dict):
                    latest_usage = usage
                # Some versions put the final text under 'result'
                final_result = event.get("result")
                if isinstance(final_result, str) and not accumulated_text_parts:
                    accumulated_text_parts.append(final_result)

            # Check for usage updates from non-result events too
            if isinstance(event.get("usage"), dict):
                latest_usage = event["usage"]
            if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                latest_usage = msg["usage"]

            if on_progress is not None:
                snapshot = {
                    "accumulated_chars": sum(len(p) for p in accumulated_text_parts),
                    "usage": latest_usage,
                    "model": latest_model,
                    "tool_activity": latest_tool_activity,  # Round 5
                }
                try:
                    await on_progress(snapshot)
                except Exception:
                    # A misbehaving callback should never crash the run
                    logger.exception("on_progress callback raised; continuing")

        # Drain stderr (non-blocking; the process should be exiting)
        try:
            stderr_bytes = await asyncio.wait_for(process.stderr.read(), timeout=5.0)
        except asyncio.TimeoutError:
            stderr_bytes = b""
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # Wait for the process to actually exit so we can read returncode
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            _kill_process(process)
            raise ClaudeTimeoutError(
                f"Claude Code CLI did not exit cleanly after stream end",
                exit_code=-1,
            )

        if process.returncode != 0:
            logger.error(
                "Claude Code CLI exited with code %d: %s",
                process.returncode, stderr[:500],
            )
            raise ClaudeRunError(
                f"Claude Code CLI exited with code {process.returncode}",
                stderr=stderr,
                exit_code=process.returncode,
            )

    except (ClaudeRunError, ClaudeTimeoutError):
        raise
    except Exception as e:
        logger.exception("Unexpected error in stream-json runner")
        _kill_process(process)
        raise ClaudeRunError(f"Stream-json runner error: {e}") from e

    logger.info(
        "Claude Code CLI completed successfully (streaming, %d chars)",
        sum(len(p) for p in accumulated_text_parts),
    )
    # Return the same dict shape as the buffered path
    return {
        "result": "".join(accumulated_text_parts),
        "usage": latest_usage,
        "model": latest_model,
    }


def _kill_process(process) -> None:
    """Best-effort kill, swallowing 'already exited' errors."""
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass
