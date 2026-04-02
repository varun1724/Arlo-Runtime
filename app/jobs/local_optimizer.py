"""Local parameter optimizer — generates strategy variants and backtests them without Claude.

Runs multiple rounds of parameter optimization via the trading engine API.
Only returns when it plateaus (no improvement for N rounds) or hits max rounds.
This replaces per-iteration Claude calls with free backtests.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import JobRow
from app.models.job import JobStatus, JobStopReason
from app.services.job_service import finalize_job, update_job_progress

logger = logging.getLogger("arlo.jobs.optimizer")

# How many parameter variants to test per round
VARIANTS_PER_ROUND = 4
# How many rounds with no improvement before declaring plateau
PLATEAU_ROUNDS = 5
# Max total rounds before forcing a Claude redesign
MAX_ROUNDS = 30


async def execute_optimize_job(session: AsyncSession, job: JobRow) -> None:
    """Run local parameter optimization: generate variants, backtest, pick best.

    Input (job.prompt): JSON with strategy_submission and optionally batch_results from prior runs.
    Output (result_data): JSON with best strategy, all results, and plateau flag.
    """
    # The prompt is the raw strategy_submission — may have extra text around JSON
    from app.jobs.trading import _parse_json_prompt
    try:
        strategy_submission = _parse_json_prompt(job.prompt)
    except (ValueError, json.JSONDecodeError) as e:
        await finalize_job(
            session, job.id,
            status=JobStatus.FAILED,
            error_message=f"Could not parse strategy JSON from prompt: {e}",
            stop_reason=JobStopReason.ERROR.value,
        )
        return

    headers = {
        "Authorization": f"Bearer {settings.trading_engine_api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.trading_engine_url

    best_sharpe = -999.0
    best_submission = strategy_submission
    best_result = None
    all_results = []
    rounds_without_improvement = 0

    for round_num in range(1, MAX_ROUNDS + 1):
        await update_job_progress(
            session, job.id,
            current_step=f"round_{round_num}",
            progress_message=f"Optimization round {round_num}/{MAX_ROUNDS} (best Sharpe: {best_sharpe:.3f}, plateau: {rounds_without_improvement}/{PLATEAU_ROUNDS})",
            iteration_count=round_num,
        )

        # Generate variants
        variants = generate_variants(best_submission, VARIANTS_PER_ROUND)
        if not variants:
            # No parameter_ranges defined — can't optimize locally
            logger.info("No parameter_ranges in strategy, skipping to Claude redesign")
            break

        # Backtest all variants in parallel
        round_results = await _backtest_variants(variants, base_url, headers)

        # Find best from this round
        round_best_sharpe = -999.0
        round_best_idx = -1
        for i, (variant, result) in enumerate(zip(variants, round_results)):
            if result is None:
                continue
            metrics = result.get("metrics") or {}
            sharpe = metrics.get("mean_sharpe_ratio", metrics.get("sharpe_ratio", -999))
            if isinstance(sharpe, (int, float)) and sharpe > round_best_sharpe:
                round_best_sharpe = sharpe
                round_best_idx = i

            all_results.append({
                "round": round_num,
                "params": variant.get("strategy", {}).get("parameters", {}),
                "sharpe": sharpe,
                "return": metrics.get("mean_total_return", 0),
                "drawdown": metrics.get("mean_max_drawdown", 1),
                "consistency": metrics.get("consistency", 0),
            })

        # Check if this round improved on the global best
        if round_best_sharpe > best_sharpe + 0.005:  # meaningful improvement
            best_sharpe = round_best_sharpe
            best_submission = variants[round_best_idx]
            best_result = round_results[round_best_idx]
            rounds_without_improvement = 0
            logger.info("Round %d: NEW BEST Sharpe %.3f", round_num, best_sharpe)
        else:
            rounds_without_improvement += 1
            logger.info("Round %d: no improvement (plateau %d/%d)", round_num, rounds_without_improvement, PLATEAU_ROUNDS)

        # Check for plateau
        if rounds_without_improvement >= PLATEAU_ROUNDS:
            logger.info("Optimizer plateaued after %d rounds at Sharpe %.3f", round_num, best_sharpe)
            break

    # Build output
    plateaued = rounds_without_improvement >= PLATEAU_ROUNDS or round_num >= MAX_ROUNDS
    output = {
        "best_strategy": best_submission,
        "best_result": best_result,
        "best_sharpe": best_sharpe,
        "total_backtests": len(all_results),
        "total_rounds": round_num,
        "plateaued": plateaued,
        "all_results_summary": _summarize_results(all_results),
        # Include the best backtest_results for the next step
        "backtest_results": best_result,
    }

    # Also check and save winners
    if best_result:
        from app.jobs.trading import _check_and_save_winner, _save_best_for_workflow
        metrics = best_result.get("metrics") or {}
        _check_and_save_winner(metrics, best_submission, str(job.id), best_result)
        if job.workflow_id:
            _save_best_for_workflow(str(job.workflow_id), metrics, best_submission, best_result)

    preview = (
        f"Optimizer: {len(all_results)} backtests over {round_num} rounds | "
        f"Best Sharpe: {best_sharpe:.3f} | "
        f"{'PLATEAUED — needs Claude redesign' if plateaued else 'Still improving'}"
    )

    await finalize_job(
        session, job.id,
        status=JobStatus.SUCCEEDED,
        result_preview=preview,
        result_data=json.dumps(output),
    )
    logger.info("Optimize job %s done: %d backtests, best Sharpe %.3f, plateaued=%s",
                job.id, len(all_results), best_sharpe, plateaued)


def generate_variants(strategy_submission: dict, n_variants: int = 8) -> list[dict]:
    """Generate parameter variations of a strategy without calling Claude.

    Reads parameter_ranges from the strategy and produces random combinations.
    Returns empty list if no parameter_ranges defined.
    """
    strategy = strategy_submission.get("strategy", {})
    base_params = strategy.get("parameters", {})
    ranges = strategy.get("parameter_ranges", {})

    if not ranges:
        return []

    variants = []
    for _ in range(n_variants):
        variant = copy.deepcopy(strategy_submission)
        new_params = dict(base_params)  # start from base

        for key, candidates in ranges.items():
            if isinstance(candidates, list) and len(candidates) > 0:
                new_params[key] = random.choice(candidates)
            elif isinstance(candidates, dict):
                # Support {"min": 10, "max": 100, "step": 10} format
                lo = candidates.get("min", 0)
                hi = candidates.get("max", 100)
                step = candidates.get("step", 1)
                if isinstance(lo, float) or isinstance(hi, float) or isinstance(step, float):
                    new_params[key] = round(random.uniform(lo, hi), 4)
                else:
                    steps = list(range(lo, hi + 1, step))
                    new_params[key] = random.choice(steps) if steps else lo

        variant["strategy"]["parameters"] = new_params
        variants.append(variant)

    return variants


async def _backtest_variants(
    variants: list[dict], base_url: str, headers: dict
) -> list[dict | None]:
    """Submit and run backtests with limited concurrency. Returns list of results."""
    # Limit to 2 concurrent backtests — walk-forward with 20yr data is heavy
    semaphore = asyncio.Semaphore(2)

    async def _run_one(variant: dict) -> dict | None:
        async with semaphore:
            try:
                strategy_data = variant.get("strategy", {})
                # Submit strategy
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{base_url}/api/strategies",
                        headers=headers,
                        json=strategy_data,
                    )
                if resp.status_code >= 400:
                    logger.warning("Failed to submit variant: %s", resp.text[:200])
                    return None

                strategy_id = resp.json()["id"]

                # Create backtest
                backtest_config = {
                    "strategy_id": strategy_id,
                    "start_date": variant.get("start_date", "2005-01-01"),
                    "end_date": variant.get("end_date", "2024-12-31"),
                    "initial_capital": variant.get("initial_capital", 1000.0),
                    "test_type": variant.get("test_type", "walk_forward"),
                }
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{base_url}/api/backtests",
                        headers=headers,
                        json=backtest_config,
                    )
                if resp.status_code >= 400:
                    logger.warning("Failed to create backtest: %s", resp.text[:200])
                    return None

                backtest_id = resp.json()["id"]

                # Run backtest — long timeout for 20yr walk-forward
                async with httpx.AsyncClient(timeout=settings.trading_timeout_seconds) as client:
                    resp = await client.post(
                        f"{base_url}/api/backtests/{backtest_id}/run",
                        headers=headers,
                    )
                if resp.status_code >= 400:
                    logger.warning("Backtest %s failed: %s", backtest_id, resp.text[:200])
                    return None

                return resp.json()

            except httpx.TimeoutException:
                logger.warning("Variant backtest timed out")
                return None
            except Exception as e:
                logger.warning("Variant backtest error: %s: %s", type(e).__name__, e)
                return None

    results = await asyncio.gather(*[_run_one(v) for v in variants])
    return list(results)


def _summarize_results(all_results: list[dict]) -> str:
    """Build a compact summary table of all backtest results for Claude to analyze."""
    if not all_results:
        return "No results"

    lines = ["Round | Params | Sharpe | Return | DD | Consistency"]
    lines.append("-" * 60)

    for r in all_results:
        params_str = ", ".join(f"{k}={v}" for k, v in r.get("params", {}).items())
        if len(params_str) > 60:
            params_str = params_str[:57] + "..."
        lines.append(
            f"R{r['round']:2d} | {params_str} | "
            f"{r.get('sharpe', -999):.3f} | "
            f"{r.get('return', 0)*100:.1f}% | "
            f"{r.get('drawdown', 1)*100:.1f}% | "
            f"{r.get('consistency', 0)*100:.0f}%"
        )

    return "\n".join(lines)
