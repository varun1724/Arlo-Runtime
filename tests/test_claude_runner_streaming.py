"""Tests for the Round 4 stream-json runner in app/services/claude_runner.py.

These tests mock ``asyncio.create_subprocess_exec`` so we never actually
spawn a Claude CLI process. Instead, a small ``FakeProcess`` class
emits a scripted sequence of stream-json lines and reports them via
``stdout.readline()`` exactly the way the real subprocess would.

The headline assertions:

1. The streaming runner assembles the same dict shape that the buffered
   runner produces — `{"result", "usage", "model"}` — so existing
   callers (research.py, builder.py) keep working.
2. The optional `on_progress` callback is invoked once per parsed event
   with a snapshot containing accumulated_chars and the latest usage.
3. Timeouts fire correctly even mid-stream.
4. Malformed JSON lines are skipped without crashing the run.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from app.services.claude_runner import (
    ClaudeRunError,
    ClaudeTimeoutError,
    _run_claude_streaming,
    run_claude,
)


# ─────────────────────────────────────────────────────────────────────
# Fake subprocess that scripts a sequence of stream-json lines
# ─────────────────────────────────────────────────────────────────────


class _FakeStreamReader:
    """Mimics asyncio.StreamReader for our purposes — yields one line at a time."""

    def __init__(self, lines: list[bytes], delay_per_line: float = 0.0):
        self._lines = list(lines)
        self._delay = delay_per_line

    async def readline(self) -> bytes:
        if self._delay:
            await asyncio.sleep(self._delay)
        if not self._lines:
            return b""
        return self._lines.pop(0)

    async def read(self, n: int = -1) -> bytes:
        return b""


class _FakeProcess:
    """Mimics asyncio.subprocess.Process: stdout/stderr readers + wait()/kill()."""

    def __init__(
        self,
        stdout_lines: list[bytes],
        returncode: int = 0,
        delay_per_line: float = 0.0,
    ):
        self.stdout = _FakeStreamReader(stdout_lines, delay_per_line)
        self.stderr = _FakeStreamReader([])
        self.returncode = returncode
        self._killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self._killed = True
        self.returncode = -9


def _line(event: dict) -> bytes:
    """JSON-encode an event and append a newline."""
    return (json.dumps(event) + "\n").encode("utf-8")


def _make_event_script(text_chunks: list[str], usage: dict | None = None) -> list[bytes]:
    """Build a realistic stream-json event sequence:
    1. system init event with model
    2. one assistant event per text chunk
    3. final result event with usage
    """
    events: list[bytes] = []
    events.append(_line({"type": "system", "subtype": "init", "model": "claude-sonnet-4"}))
    for chunk in text_chunks:
        events.append(_line({
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": chunk}],
            },
        }))
    final: dict = {"type": "result", "result": "".join(text_chunks)}
    if usage is not None:
        final["usage"] = usage
    events.append(_line(final))
    return events


# ─────────────────────────────────────────────────────────────────────
# Headline test: streaming assembles the same dict shape
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streaming_assembles_full_result():
    fake = _FakeProcess(_make_event_script(
        text_chunks=["Hello, ", "world!"],
        usage={"input_tokens": 100, "output_tokens": 50},
    ))

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = await _run_claude_streaming(
            ["claude", "-p", "test"],
            cwd=None,
            timeout=10,
            on_progress=None,
        )

    assert result["result"] == "Hello, world!"
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert result["model"] == "claude-sonnet-4"


@pytest.mark.asyncio
async def test_streaming_returns_same_shape_as_buffered():
    """Sanity: the result dict has the keys the existing callers expect."""
    fake = _FakeProcess(_make_event_script(["x"], usage={"input_tokens": 1, "output_tokens": 1}))

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=None,
        )

    assert set(result.keys()) >= {"result", "usage", "model"}


# ─────────────────────────────────────────────────────────────────────
# Progress callback
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streaming_calls_on_progress_per_event():
    snapshots: list[dict] = []

    async def progress_cb(snap: dict) -> None:
        snapshots.append(dict(snap))

    fake = _FakeProcess(_make_event_script(
        ["aaa", "bbb", "cccc"],
        usage={"input_tokens": 10, "output_tokens": 5},
    ))

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=progress_cb,
        )

    # 1 system init + 3 assistant + 1 result = 5 events total
    assert len(snapshots) == 5
    # Accumulated chars grows monotonically
    char_counts = [s["accumulated_chars"] for s in snapshots]
    assert char_counts == sorted(char_counts)
    # Final snapshot has the full content length
    assert snapshots[-1]["accumulated_chars"] == len("aaabbbcccc")
    # Usage shows up by the final snapshot
    assert snapshots[-1]["usage"] == {"input_tokens": 10, "output_tokens": 5}


@pytest.mark.asyncio
async def test_streaming_progress_callback_exception_does_not_crash():
    """A misbehaving callback should never kill the run."""

    async def bad_cb(snap: dict) -> None:
        raise RuntimeError("callback exploded")

    fake = _FakeProcess(_make_event_script(["x"], usage={"input_tokens": 1, "output_tokens": 1}))

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=bad_cb,
        )

    # The run still completes successfully despite the callback exploding
    assert result["result"] == "x"


# ─────────────────────────────────────────────────────────────────────
# Error paths
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streaming_handles_malformed_json_lines():
    """A malformed line in the middle of the stream is skipped, not fatal."""
    events = _make_event_script(
        ["good chunk"],
        usage={"input_tokens": 1, "output_tokens": 1},
    )
    # Inject a garbage line between the good events
    events.insert(1, b"this is not json\n")

    fake = _FakeProcess(events)

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=None,
        )

    assert result["result"] == "good chunk"


@pytest.mark.asyncio
async def test_streaming_handles_empty_lines():
    """Empty lines (e.g. trailing newlines) shouldn't cause parser errors."""
    events = _make_event_script(["x"], usage={"input_tokens": 1, "output_tokens": 1})
    events.insert(1, b"\n")
    events.insert(2, b"   \n")

    fake = _FakeProcess(events)

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        result = await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=None,
        )

    assert result["result"] == "x"


@pytest.mark.asyncio
async def test_streaming_nonzero_exit_raises_runerror():
    fake = _FakeProcess(_make_event_script(["x"]), returncode=1)

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        with pytest.raises(ClaudeRunError) as exc:
            await _run_claude_streaming(
                ["claude"], cwd=None, timeout=5, on_progress=None,
            )
        assert "exited with code 1" in str(exc.value)


@pytest.mark.asyncio
async def test_streaming_respects_timeout_on_slow_lines():
    """Slow stdout reads should trip the deadline."""
    # Each line takes 2 seconds; with timeout=1 we should fail before
    # the first line is fully read.
    fake = _FakeProcess(
        _make_event_script(["x"], usage={"input_tokens": 1, "output_tokens": 1}),
        delay_per_line=2.0,
    )

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        with pytest.raises(ClaudeTimeoutError):
            await _run_claude_streaming(
                ["claude"], cwd=None, timeout=1, on_progress=None,
            )


# ─────────────────────────────────────────────────────────────────────
# Round 5: tool_use / tool_result event handling
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_streaming_tool_use_event_populates_tool_activity():
    """A top-level tool_use event should set tool_activity in snapshots."""
    snapshots: list[dict] = []

    async def progress_cb(snap: dict) -> None:
        snapshots.append(dict(snap))

    events = [
        _line({"type": "system", "subtype": "init", "model": "claude-sonnet-4"}),
        _line({"type": "tool_use", "name": "WebSearch"}),
        _line({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "found it"}]},
        }),
        _line({"type": "result", "result": "found it",
               "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ]
    fake = _FakeProcess(events)

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=progress_cb,
        )

    # After the tool_use event, the snapshot should report the activity
    activities = [s.get("tool_activity") for s in snapshots]
    assert "Using WebSearch" in activities


@pytest.mark.asyncio
async def test_streaming_tool_result_clears_tool_activity():
    """tool_result should clear the activity marker (back to text generation)."""
    snapshots: list[dict] = []

    async def progress_cb(snap: dict) -> None:
        snapshots.append(dict(snap))

    events = [
        _line({"type": "system", "subtype": "init", "model": "claude-sonnet-4"}),
        _line({"type": "tool_use", "name": "WebSearch"}),
        _line({"type": "tool_result"}),
        _line({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "done"}]},
        }),
        _line({"type": "result", "result": "done",
               "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ]
    fake = _FakeProcess(events)

    async def fake_create(*args, **kwargs):
        return fake

    with patch("app.services.claude_runner.asyncio.create_subprocess_exec", side_effect=fake_create):
        await _run_claude_streaming(
            ["claude"], cwd=None, timeout=5, on_progress=progress_cb,
        )

    # The last snapshot (after assistant text following tool_result) should have None
    assert snapshots[-1].get("tool_activity") is None
    # But there was a moment when tool_activity was set
    activities = [s.get("tool_activity") for s in snapshots]
    assert "Using WebSearch" in activities
