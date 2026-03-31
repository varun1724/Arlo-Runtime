"""Trading engine job executor — submits strategies and backtests to the trading engine API."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.trading")


class TradingEngineError(Exception):
    pass


async def execute_trading_job(session: AsyncSession, job: JobRow) -> None:
    """Execute a trading job by calling the trading engine API."""
    try:
        instructions = _parse_json_prompt(job.prompt)
    except ValueError as e:
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=f"Invalid trading job prompt: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )
        return

    action = instructions.get("action", "")
    headers = {
        "Authorization": f"Bearer {settings.trading_engine_api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.trading_engine_url

    try:
        if action == "submit_strategy":
            await _submit_strategy(session, job, instructions, base_url, headers)

        elif action == "run_backtest":
            await _run_backtest(session, job, instructions, base_url, headers)

        elif action == "submit_and_backtest":
            # Combined: submit strategy then immediately backtest
            strategy_id = await _submit_strategy_raw(instructions, base_url, headers)
            instructions["strategy_id"] = strategy_id
            await _run_backtest(session, job, instructions, base_url, headers)

        else:
            await finalize_job(
                session, job.id,
                status=JobStatus.FAILED,
                error_message=f"Unknown trading action: {action}",
                stop_reason=JobStopReason.ERROR.value,
            )

    except TradingEngineError as e:
        logger.error("Trading job %s failed: %s", job.id, e)
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=str(e),
            stop_reason=JobStopReason.ERROR.value,
        )
    except Exception as e:
        logger.exception("Trading job %s failed unexpectedly", job.id)
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=str(e),
            stop_reason=JobStopReason.ERROR.value,
        )


async def _submit_strategy_raw(
    instructions: dict, base_url: str, headers: dict
) -> str:
    """Submit a strategy and return its ID."""
    strategy_data = instructions.get("strategy", {})
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}/api/strategies", headers=headers, json=strategy_data)
    if resp.status_code >= 400:
        raise TradingEngineError(f"Failed to submit strategy: {resp.status_code} {resp.text[:500]}")
    return resp.json()["id"]


def _parse_json_prompt(text: str) -> dict:
    """Parse JSON from a prompt that may have extra text around it.

    Claude sometimes adds explanation text before or after the JSON.
    This extracts the JSON object by finding the outermost { }.
    """
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        first_nl = text.index("\n")
        text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3].strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the outermost JSON object by matching braces
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in prompt")

    depth = 0
    in_string = False
    escape = False
    end = start

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    json_str = text[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse extracted JSON: {e}")


async def _submit_strategy(
    session: AsyncSession, job: JobRow, instructions: dict, base_url: str, headers: dict
) -> None:
    """Submit a strategy to the trading engine."""
    await update_job_progress(
        session, job.id,
        current_step="submitting",
        progress_message="Submitting strategy to trading engine",
        iteration_count=1,
    )

    strategy_id = await _submit_strategy_raw(instructions, base_url, headers)

    await finalize_job(
        session, job.id,
        status=JobStatus.SUCCEEDED,
        result_preview=f"Strategy submitted: {strategy_id}",
        result_data=json.dumps({"strategy_id": strategy_id}),
    )


async def _run_backtest(
    session: AsyncSession, job: JobRow, instructions: dict, base_url: str, headers: dict
) -> None:
    """Submit a backtest, poll for completion, return results."""
    strategy_id = instructions.get("strategy_id")
    if not strategy_id:
        raise TradingEngineError("No strategy_id provided for backtest")

    backtest_config = {
        "strategy_id": strategy_id,
        "start_date": instructions.get("start_date", "2016-01-01"),
        "end_date": instructions.get("end_date", "2024-12-31"),
        "initial_capital": instructions.get("initial_capital", 1000.0),
        "test_type": instructions.get("test_type", "walk_forward"),
    }

    await update_job_progress(
        session, job.id,
        current_step="creating_backtest",
        progress_message="Creating backtest on trading engine",
        iteration_count=1,
    )

    # Create backtest
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{base_url}/api/backtests", headers=headers, json=backtest_config)
    if resp.status_code >= 400:
        raise TradingEngineError(f"Failed to create backtest: {resp.status_code} {resp.text[:500]}")

    backtest_id = resp.json()["id"]

    await update_job_progress(
        session, job.id,
        current_step="running_backtest",
        progress_message="Running backtest (this may take a moment)",
        iteration_count=2,
    )

    # Run backtest
    async with httpx.AsyncClient(timeout=settings.trading_timeout_seconds) as client:
        resp = await client.post(f"{base_url}/api/backtests/{backtest_id}/run", headers=headers)
    if resp.status_code >= 400:
        raise TradingEngineError(f"Backtest failed: {resp.status_code} {resp.text[:500]}")

    result = resp.json()

    await update_job_progress(
        session, job.id,
        current_step="processing_results",
        progress_message="Processing backtest results",
        iteration_count=3,
    )

    # Build preview
    metrics = result.get("metrics", {})
    preview = _build_preview(metrics, result.get("benchmark_metrics", {}))

    await finalize_job(
        session, job.id,
        status=JobStatus.SUCCEEDED,
        result_preview=preview,
        result_data=json.dumps(result),
    )
    logger.info("Trading job %s completed: backtest %s", job.id, backtest_id)


def _build_preview(metrics: dict, benchmark: dict) -> str:
    """Build a human-readable preview of backtest results."""
    lines = []
    sharpe = metrics.get("mean_sharpe_ratio", metrics.get("sharpe_ratio", 0))
    ret = metrics.get("mean_total_return", metrics.get("total_return", 0))
    dd = metrics.get("mean_max_drawdown", metrics.get("max_drawdown", 0))
    consistency = metrics.get("consistency")

    lines.append(f"Return: {ret*100:.1f}% | Sharpe: {sharpe:.3f} | MaxDD: {dd*100:.1f}%")
    if consistency is not None:
        lines.append(f"Walk-forward consistency: {consistency*100:.0f}%")

    bench_ret = benchmark.get("total_return", 0) if benchmark else 0
    if bench_ret:
        lines.append(f"Benchmark (SPY): {bench_ret*100:.1f}%")

    return " | ".join(lines) if lines else "Backtest completed"
