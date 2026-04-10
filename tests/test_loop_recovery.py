"""Tests for the contrarian -> landscape recovery loop (Round 3).

Two layers, mirroring how Round 2's retry tests are structured:

1. **Pure unit tests** for ``_count_survivors`` and the new
   ``survivor_count_below`` condition operator. These run with --noconftest.

2. **No DB-bound integration tests** in this file — the actual loop_to
   firing in ``advance_workflow`` is exercised end-to-end during the
   post-deploy verification run. The pure helpers below cover the
   decision logic completely.
"""

from __future__ import annotations

import json

import pytest

from app.models.workflow import StepCondition
from app.services.workflow_service import _count_survivors, _evaluate_condition


# ─────────────────────────────────────────────────────────────────────
# _count_survivors
# ─────────────────────────────────────────────────────────────────────


def test_count_survivors_none_input():
    assert _count_survivors(None) == 0


def test_count_survivors_empty_dict():
    assert _count_survivors({}) == 0


def test_count_survivors_empty_string():
    assert _count_survivors("") == 0


def test_count_survivors_invalid_json_string():
    assert _count_survivors("not json at all") == 0


def test_count_survivors_string_input_all_killed():
    payload = json.dumps({
        "contrarian_analyses": [
            {"name": "a", "verdict": "killed"},
            {"name": "b", "verdict": "killed"},
            {"name": "c", "verdict": "killed"},
        ],
        "summary": "all dead",
    })
    assert _count_survivors(payload) == 0


def test_count_survivors_string_input_two_survivors():
    payload = json.dumps({
        "contrarian_analyses": [
            {"name": "a", "verdict": "survives"},
            {"name": "b", "verdict": "weakened"},
            {"name": "c", "verdict": "killed"},
        ],
    })
    assert _count_survivors(payload) == 2


def test_count_survivors_dict_input():
    payload = {
        "contrarian_analyses": [
            {"name": "a", "verdict": "survives"},
            {"name": "b", "verdict": "survives"},
            {"name": "c", "verdict": "weakened"},
            {"name": "d", "verdict": "killed"},
        ],
    }
    assert _count_survivors(payload) == 3


def test_count_survivors_missing_analyses_key():
    assert _count_survivors({"summary": "x"}) == 0


def test_count_survivors_analyses_not_a_list():
    assert _count_survivors({"contrarian_analyses": "not a list"}) == 0


def test_count_survivors_skips_non_dict_entries():
    payload = {
        "contrarian_analyses": [
            "not a dict",
            {"verdict": "survives"},
            42,
            {"verdict": "killed"},
        ],
    }
    assert _count_survivors(payload) == 1


# ─────────────────────────────────────────────────────────────────────
# survivor_count_below operator
# ─────────────────────────────────────────────────────────────────────


def _make_contrarian_context(survivor_count: int, killed_count: int = 0) -> dict:
    analyses = (
        [{"name": f"s{i}", "verdict": "survives"} for i in range(survivor_count)]
        + [{"name": f"k{i}", "verdict": "killed"} for i in range(killed_count)]
    )
    return {"contrarian": json.dumps({"contrarian_analyses": analyses})}


def test_survivor_count_below_fires_when_threshold_not_met():
    """0 survivors < threshold 3 → loop should fire."""
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="3")
    ctx = _make_contrarian_context(survivor_count=0, killed_count=5)
    assert _evaluate_condition(cond, ctx) is True


def test_survivor_count_below_does_not_fire_at_threshold():
    """3 survivors == threshold 3 → loop should NOT fire (strictly below)."""
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="3")
    ctx = _make_contrarian_context(survivor_count=3)
    assert _evaluate_condition(cond, ctx) is False


def test_survivor_count_below_does_not_fire_when_above_threshold():
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="3")
    ctx = _make_contrarian_context(survivor_count=5)
    assert _evaluate_condition(cond, ctx) is False


def test_survivor_count_below_handles_one_survivor_below_three():
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="3")
    ctx = _make_contrarian_context(survivor_count=1, killed_count=4)
    assert _evaluate_condition(cond, ctx) is True


def test_survivor_count_below_invalid_threshold_returns_false():
    """A garbage threshold defaults to false (don't loop accidentally)."""
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="not a number")
    ctx = _make_contrarian_context(survivor_count=0)
    assert _evaluate_condition(cond, ctx) is False


def test_survivor_count_below_no_contrarian_in_context():
    """Missing context key → 0 survivors → loop fires (recovery mode)."""
    cond = StepCondition(field="contrarian", operator="survivor_count_below", value="3")
    assert _evaluate_condition(cond, {}) is True


# ─────────────────────────────────────────────────────────────────────
# Template wiring sanity checks
# ─────────────────────────────────────────────────────────────────────


def test_contrarian_template_has_loop_back_config():
    """Round 3: contrarian step in startup_idea_pipeline must have the
    recovery loop wired up."""
    from app.models.workflow import StepDefinition
    from app.workflows.templates import STARTUP_IDEA_PIPELINE

    contrarian = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "contrarian_analysis"
    )
    sd = StepDefinition.model_validate(contrarian)
    assert sd.loop_to == 0, "contrarian must loop back to landscape (step 0)"
    assert sd.max_loop_count == 2, "max 2 retries to avoid infinite loops"
    assert sd.loop_condition is not None
    assert sd.loop_condition.operator == "survivor_count_below"
    assert sd.loop_condition.value == "3"


def test_landscape_prompt_references_recovery_flag():
    """The landscape prompt must read previous_attempt_killed_all so it can
    broaden the search on a recovery loop."""
    from app.workflows.templates import STARTUP_IDEA_PIPELINE

    landscape = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "landscape_scan"
    )
    template = landscape["prompt_template"]
    assert "previous_attempt_killed_all" in template
    assert "RECOVERY MODE" in template


# ─────────────────────────────────────────────────────────────────────
# Round 4: loop count boundary math
# ─────────────────────────────────────────────────────────────────────
#
# The actual check in advance_workflow is:
#     loop_count = <count of jobs at step_index=loop_to>
#     if loop_count < current_step.max_loop_count:
#         next_index = current_step.loop_to
#
# This means max_loop_count counts EXECUTIONS of the loop_to step
# (including the initial run), not LOOP ITERATIONS. These tests
# document that semantics by simulating the count math directly.


def _should_loop_back(loop_count: int, max_loop_count: int) -> bool:
    """Mirror of the boundary check in advance_workflow."""
    return loop_count < max_loop_count


def test_loop_count_boundary_max_two_allows_one_loop():
    """max_loop_count=2 → after first run (count=1) the loop fires once;
    after the second run (count=2) the loop does NOT fire again."""
    # First run completes — loop_count is now 1 (this run)
    assert _should_loop_back(loop_count=1, max_loop_count=2) is True
    # Second run completes — loop_count is now 2
    assert _should_loop_back(loop_count=2, max_loop_count=2) is False
    # We never reach 3 because the loop didn't fire on the second pass.


def test_loop_count_max_one_disables_loop():
    """max_loop_count=1 means: run once, never loop. After the first run
    completes, loop_count=1 and 1 < 1 is False."""
    assert _should_loop_back(loop_count=1, max_loop_count=1) is False


def test_loop_count_max_three_allows_two_loops():
    """max_loop_count=3 → 3 total executions of the loop_to step
    (initial + 2 loops)."""
    assert _should_loop_back(loop_count=1, max_loop_count=3) is True
    assert _should_loop_back(loop_count=2, max_loop_count=3) is True
    assert _should_loop_back(loop_count=3, max_loop_count=3) is False
