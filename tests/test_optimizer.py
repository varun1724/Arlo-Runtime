"""Tests for the local parameter optimizer."""

import json
import copy

import pytest


def test_generate_variants_with_list_ranges():
    """generate_variants produces correct number of variants with list ranges."""
    from app.jobs.local_optimizer import generate_variants

    submission = {
        "action": "submit_and_backtest",
        "strategy": {
            "name": "Test Strategy",
            "strategy_code": "class Foo: pass",
            "parameters": {"lookback": 63, "sma_period": 200, "vix_threshold": 25},
            "parameter_ranges": {
                "lookback": [21, 42, 63, 126, 252],
                "sma_period": [50, 100, 150, 200],
                "vix_threshold": [15, 20, 25, 30, 35],
            },
            "symbols": ["SPY"],
        },
        "start_date": "2005-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 1000,
        "test_type": "walk_forward",
    }

    variants = generate_variants(submission, n_variants=10)
    assert len(variants) == 10

    for v in variants:
        params = v["strategy"]["parameters"]
        assert params["lookback"] in [21, 42, 63, 126, 252]
        assert params["sma_period"] in [50, 100, 150, 200]
        assert params["vix_threshold"] in [15, 20, 25, 30, 35]
        # strategy_code should be preserved
        assert v["strategy"]["strategy_code"] == "class Foo: pass"
        # other fields preserved
        assert v["start_date"] == "2005-01-01"
        assert v["initial_capital"] == 1000


def test_generate_variants_with_dict_ranges():
    """generate_variants handles min/max/step range format."""
    from app.jobs.local_optimizer import generate_variants

    submission = {
        "strategy": {
            "name": "Test",
            "strategy_code": "pass",
            "parameters": {"lookback": 63},
            "parameter_ranges": {
                "lookback": {"min": 20, "max": 100, "step": 20},
            },
        },
    }

    variants = generate_variants(submission, n_variants=5)
    assert len(variants) == 5
    for v in variants:
        lb = v["strategy"]["parameters"]["lookback"]
        assert 20 <= lb <= 100


def test_generate_variants_empty_ranges():
    """generate_variants returns empty list when no parameter_ranges."""
    from app.jobs.local_optimizer import generate_variants

    submission = {
        "strategy": {
            "name": "Test",
            "strategy_code": "pass",
            "parameters": {"lookback": 63},
            # no parameter_ranges
        },
    }

    variants = generate_variants(submission, n_variants=5)
    assert variants == []


def test_generate_variants_preserves_non_range_params():
    """Parameters without ranges keep their original values."""
    from app.jobs.local_optimizer import generate_variants

    submission = {
        "strategy": {
            "name": "Test",
            "strategy_code": "pass",
            "parameters": {"lookback": 63, "fixed_param": "abc"},
            "parameter_ranges": {
                "lookback": [21, 42],
            },
        },
    }

    variants = generate_variants(submission, n_variants=5)
    for v in variants:
        assert v["strategy"]["parameters"]["fixed_param"] == "abc"
        assert v["strategy"]["parameters"]["lookback"] in [21, 42]


def test_generate_variants_deep_copy():
    """Variants don't share references with original."""
    from app.jobs.local_optimizer import generate_variants

    submission = {
        "strategy": {
            "name": "Test",
            "strategy_code": "pass",
            "parameters": {"lookback": 63},
            "parameter_ranges": {"lookback": [21, 42]},
        },
    }

    variants = generate_variants(submission, n_variants=3)
    # Mutate a variant — shouldn't affect others
    variants[0]["strategy"]["parameters"]["lookback"] = 999
    assert variants[1]["strategy"]["parameters"]["lookback"] != 999
    assert submission["strategy"]["parameters"]["lookback"] == 63


def test_summarize_results():
    """_summarize_results produces readable output."""
    from app.jobs.local_optimizer import _summarize_results

    results = [
        {"round": 1, "params": {"lookback": 21, "sma": 100}, "sharpe": 0.5, "return": 0.08, "drawdown": 0.15, "consistency": 0.6},
        {"round": 1, "params": {"lookback": 63, "sma": 200}, "sharpe": 0.8, "return": 0.12, "drawdown": 0.18, "consistency": 0.8},
    ]

    summary = _summarize_results(results)
    assert "0.500" in summary
    assert "0.800" in summary
    assert "R 1" in summary
    assert "lookback" in summary


def test_summarize_results_empty():
    from app.jobs.local_optimizer import _summarize_results
    assert _summarize_results([]) == "No results"


def test_pipeline_template_structure():
    """Verify the new evolution pipeline has the right structure."""
    from app.workflows.templates import STRATEGY_EVOLUTION_PIPELINE

    steps = STRATEGY_EVOLUTION_PIPELINE["steps"]
    assert len(steps) == 3

    # Step 0: generate_strategy (Claude)
    assert steps[0]["name"] == "generate_strategy"
    assert steps[0]["job_type"] == "research"
    assert "parameter_ranges" in steps[0]["prompt_template"]

    # Step 1: local_optimize (no Claude)
    assert steps[1]["name"] == "local_optimize"
    assert steps[1]["job_type"] == "optimize"
    assert steps[1]["output_key"] == "optimizer_results"

    # Step 2: evaluate_and_redesign (Claude, loops back)
    assert steps[2]["name"] == "evaluate_and_redesign"
    assert steps[2]["job_type"] == "research"
    assert steps[2]["loop_to"] == 1
    assert steps[2]["max_loop_count"] == 50


def test_pipeline_optional_context_includes_research():
    """Verify strategy_research is in optional context for pre-population."""
    from app.workflows.templates import STRATEGY_EVOLUTION_PIPELINE
    assert "strategy_research" in STRATEGY_EVOLUTION_PIPELINE["optional_context"]


def test_optimize_job_type_exists():
    """Verify the optimize job type is registered."""
    from app.models.job import JobType
    assert JobType.OPTIMIZE == "optimize"
    assert JobType("optimize") == JobType.OPTIMIZE


def test_cached_research_valid_json():
    """Verify the cached research file is valid JSON with expected structure."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "workspaces", "cached_research.json")
    if not os.path.exists(path):
        pytest.skip("cached_research.json not in local filesystem")

    with open(path) as f:
        data = json.load(f)

    assert "strategies" in data
    assert "recommendation" in data
    assert len(data["strategies"]) >= 5
    for s in data["strategies"]:
        assert "name" in s
        assert "historical_sharpe" in s
        assert "instruments" in s
