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
        # Don't fail — return bad metrics so the evolution loop continues
        logger.warning("Trading job %s: bad JSON prompt, returning penalty metrics", job.id)
        penalty_result = json.dumps({
            "status": "failed",
            "metrics": {"mean_sharpe_ratio": -999, "mean_total_return": 0, "mean_max_drawdown": 1.0, "consistency": 0, "total_trades_all_folds": 0},
            "error_message": f"Strategy code produced invalid JSON: {str(e)[:200]}",
        })
        await finalize_job(
            session, job.id,
            status=JobStatus.SUCCEEDED,
            result_preview="Strategy code error — returning penalty metrics for evolution",
            result_data=penalty_result,
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

    except (TradingEngineError, Exception) as e:
        logger.error("Trading job %s error: %s", job.id, e)
        # Return penalty metrics instead of failing — keeps the evolution loop alive
        penalty_result = json.dumps({
            "status": "failed",
            "metrics": {"mean_sharpe_ratio": -999, "mean_total_return": 0, "mean_max_drawdown": 1.0, "consistency": 0, "total_trades_all_folds": 0},
            "error_message": str(e)[:500],
        })
        await finalize_job(
            session, job.id,
            status=JobStatus.SUCCEEDED,
            result_preview=f"Backtest error — penalty metrics: {str(e)[:100]}",
            result_data=penalty_result,
        )
        return



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

    # If the backtest itself failed (strategy error), still store results
    # so the evolution loop can analyze what went wrong
    if result.get("status") == "failed":
        error_msg = result.get("error_message", "Strategy failed during backtest")
        result["metrics"] = result.get("metrics") or {"error": error_msg, "sharpe_ratio": -999, "total_return": 0, "max_drawdown": 1.0}

    await update_job_progress(
        session, job.id,
        current_step="processing_results",
        progress_message="Processing backtest results",
        iteration_count=3,
    )

    # Build preview
    metrics = result.get("metrics", {})
    preview = _build_preview(metrics, result.get("benchmark_metrics", {}))

    # Auto-save if strategy passes qualifying thresholds (including worst-fold check)
    _check_and_save_winner(metrics, instructions, str(job.id), result)

    # Always save best-so-far per workflow (survives credit exhaustion)
    if job.workflow_id:
        _save_best_for_workflow(str(job.workflow_id), metrics, instructions, result)

    await finalize_job(
        session, job.id,
        status=JobStatus.SUCCEEDED,
        result_preview=preview,
        result_data=json.dumps(result),
    )
    logger.info("Trading job %s completed: backtest %s", job.id, backtest_id)


# Track best Sharpe per workflow — only overwritten when a BETTER result is found
_best_sharpe_per_workflow: dict[str, float] = {}
_highest_winner_sharpe: float = 0.0


def _save_best_for_workflow(workflow_id: str, metrics: dict, instructions: dict, full_result: dict) -> None:
    """Save the best strategy for each workflow. Only overwrites when Sharpe improves."""
    from pathlib import Path

    sharpe = metrics.get("mean_sharpe_ratio", metrics.get("sharpe_ratio", -999))
    if not isinstance(sharpe, (int, float)) or sharpe <= 0:
        return  # skip bad results

    prev_best = _best_sharpe_per_workflow.get(workflow_id, 0)
    if sharpe <= prev_best:
        return  # not an improvement

    _best_sharpe_per_workflow[workflow_id] = sharpe

    save_dir = Path("/workspaces/best_strategies")
    save_dir.mkdir(parents=True, exist_ok=True)

    filepath = save_dir / f"best_{workflow_id[:8]}.json"
    save_data = {
        "workflow_id": workflow_id,
        "sharpe": sharpe,
        "metrics": metrics,
        "strategy_submission": instructions,
        "backtest_results": full_result,
    }

    with open(filepath, "w") as f:
        json.dump(save_data, f, indent=2)

    logger.info("New best for workflow %s: Sharpe %.3f → saved to %s", workflow_id[:8], sharpe, filepath)


QUALIFYING_THRESHOLDS = {
    "sharpe_min": 0.8,
    "mean_return_min": 0.10,  # must beat 10% annualized (SPY baseline)
    "max_drawdown_max": 0.20,
    "consistency_min": 0.75,
    "min_trades": 30,
    "worst_fold_return_min": -0.15,
}


def _check_and_save_winner(metrics: dict, instructions: dict, job_id: str, full_result: dict = None) -> None:
    """Check if backtest metrics pass all thresholds including worst-fold. If yes, save to disk."""
    import os
    from datetime import datetime
    from pathlib import Path

    sharpe = metrics.get("mean_sharpe_ratio", metrics.get("sharpe_ratio", -999))
    drawdown = metrics.get("mean_max_drawdown", metrics.get("max_drawdown", 1.0))
    consistency = metrics.get("consistency", 0)
    trades = metrics.get("total_trades_all_folds", metrics.get("total_trades", 0))

    # Check worst fold
    worst_fold_ok = True
    if full_result and isinstance(full_result, dict):
        fold_config = full_result.get("fold_config", {})
        if isinstance(fold_config, dict):
            folds = fold_config.get("folds", [])
            for fold in folds:
                fold_metrics = fold.get("metrics", {})
                fold_return = fold_metrics.get("total_return", 0)
                if fold_return < QUALIFYING_THRESHOLDS.get("worst_fold_return_min", -0.15):
                    worst_fold_ok = False
                    break

    mean_return = metrics.get("mean_total_return", 0)

    passes = (
        sharpe >= QUALIFYING_THRESHOLDS["sharpe_min"]
        and mean_return >= QUALIFYING_THRESHOLDS.get("mean_return_min", 0.10)
        and drawdown <= QUALIFYING_THRESHOLDS["max_drawdown_max"]
        and consistency >= QUALIFYING_THRESHOLDS["consistency_min"]
        and trades >= QUALIFYING_THRESHOLDS["min_trades"]
        and worst_fold_ok
    )

    if not passes:
        return

    # Only save if this is a new high Sharpe (avoid duplicates)
    global _highest_winner_sharpe
    if sharpe <= _highest_winner_sharpe:
        return
    _highest_winner_sharpe = sharpe

    # Save winning strategy
    save_dir = Path("/workspaces/winning_strategies")
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"winner_{timestamp}_sharpe{sharpe:.3f}.json"
    filepath = save_dir / filename

    strategy_data = instructions.get("strategy", {})
    save_data = {
        "timestamp": timestamp,
        "job_id": job_id,
        "metrics": metrics,
        "strategy": strategy_data,
        "thresholds_passed": {
            "sharpe": f"{sharpe:.4f} >= {QUALIFYING_THRESHOLDS['sharpe_min']}",
            "drawdown": f"{drawdown:.4f} <= {QUALIFYING_THRESHOLDS['max_drawdown_max']}",
            "consistency": f"{consistency:.4f} >= {QUALIFYING_THRESHOLDS['consistency_min']}",
            "trades": f"{trades} >= {QUALIFYING_THRESHOLDS['min_trades']}",
        },
    }

    with open(filepath, "w") as f:
        json.dump(save_data, f, indent=2)

    logger.info(
        "*** WINNING STRATEGY FOUND *** Sharpe=%.4f, saved to %s",
        sharpe, filepath,
    )


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
