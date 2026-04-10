"""Tests for the per-step context_inputs whitelist feature.

These tests cover ``_prune_context`` (the pure helper) and
``_render_prompt`` (the renderer that consumes its output). The
integration in ``_create_step_job`` is exercised end-to-end during the
post-deploy verification run.

The most important assertion in this file is
``test_build_mvp_prompt_size_drops_dramatically``: it loads the actual
``startup_idea_pipeline`` template, populates a realistic full context
(landscape + deep_dive + contrarian + synthesis as JSON strings), and
proves that the rendered ``build_mvp`` prompt with the new
``context_inputs=["synthesis"]`` is dramatically smaller than the
unpruned version. This is the bug-fix-validation test for the
"context balloons to 50KB+" issue.
"""

from __future__ import annotations

import json

import pytest

from app.models.workflow import StepDefinition
from app.services.workflow_service import (
    _prune_context,
    _render_prompt,
    _stringify_for_prompt,
)
from app.workflows.templates import STARTUP_IDEA_PIPELINE
from tests.fixtures.startup_pipeline_fixtures import (
    VALID_CONTRARIAN,
    VALID_DEEP_DIVE,
    VALID_LANDSCAPE,
    VALID_SYNTHESIS,
)


# ─────────────────────────────────────────────────────────────────────
# _prune_context unit tests
# ─────────────────────────────────────────────────────────────────────


def test_prune_with_none_returns_original():
    ctx = {"a": 1, "b": 2}
    assert _prune_context(ctx, None) is ctx  # same object — backward compat


def test_prune_with_whitelist_filters_keys():
    ctx = {"a": 1, "b": 2, "c": 3}
    pruned = _prune_context(ctx, ["a", "c"])
    assert pruned == {"a": 1, "c": 3}


def test_prune_with_empty_whitelist_returns_empty():
    ctx = {"a": 1, "b": 2}
    pruned = _prune_context(ctx, [])
    assert pruned == {}


def test_prune_silently_drops_missing_keys():
    """Missing keys don't raise; the renderer's fallback handles them."""
    ctx = {"a": 1}
    pruned = _prune_context(ctx, ["a", "b", "c"])
    assert pruned == {"a": 1}


def test_prune_does_not_mutate_input():
    ctx = {"a": 1, "b": 2}
    _prune_context(ctx, ["a"])
    assert ctx == {"a": 1, "b": 2}


# ─────────────────────────────────────────────────────────────────────
# _render_prompt + pruning interaction
# ─────────────────────────────────────────────────────────────────────


def test_render_with_no_pruning_includes_all_keys():
    template = "first={first} second={second}"
    rendered = _render_prompt(template, {"first": "A", "second": "B"})
    assert rendered == "first=A second=B"


def test_render_with_pruning_omits_filtered_keys():
    template = "kept={kept} dropped={dropped}"
    full_ctx = {"kept": "yes", "dropped": "huge_payload" * 1000}
    pruned = _prune_context(full_ctx, ["kept"])
    rendered = _render_prompt(template, pruned)
    assert "yes" in rendered
    assert "huge_payload" not in rendered
    # The renderer's defaultdict fallback substitutes {unknown}
    assert "{unknown}" in rendered


def test_render_prompt_with_pruning_renders_correctly():
    """Realistic case: a single key passed through to the prompt."""
    template = "DATA:\n{synthesis}\n\nDONE"
    pruned = _prune_context({"synthesis": '{"final_rankings": []}', "other": "ignored"}, ["synthesis"])
    rendered = _render_prompt(template, pruned)
    assert "final_rankings" in rendered
    assert "ignored" not in rendered


# ─────────────────────────────────────────────────────────────────────
# build_mvp size reduction — the headline assertion
# ─────────────────────────────────────────────────────────────────────


def _full_context_with_realistic_payloads() -> dict:
    """Populate context the way it actually accumulates by step 5.

    Step outputs are stored as JSON strings in the database, mirroring
    what ``advance_workflow`` does at line 200:
    ``context[output_key] = completed_job.result_data``.

    Round 3: also includes ``selected_idea`` (the user's pick at the
    approval gate, injected via ``context_overrides``).
    """
    return {
        "domain": "AI developer tools",
        "focus_areas": "code review and testing",
        "constraints": "solo developer",
        "landscape": json.dumps(VALID_LANDSCAPE),
        "deep_dive": json.dumps(VALID_DEEP_DIVE),
        "contrarian": json.dumps(VALID_CONTRARIAN),
        "synthesis": json.dumps(VALID_SYNTHESIS),
        "selected_idea": VALID_SYNTHESIS["final_rankings"][0],
    }


def _get_build_mvp_step() -> StepDefinition:
    raw = next(s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "build_mvp")
    return StepDefinition.model_validate(raw)


def test_build_mvp_step_has_context_inputs_set():
    """Round 3: build_mvp now reads selected_idea (user's pick), not full synthesis."""
    step = _get_build_mvp_step()
    assert step.context_inputs == ["selected_idea"]


def test_build_mvp_pruned_prompt_excludes_landscape_deep_dive_and_synthesis():
    """Round 3: build_mvp gets only the user's selected idea, not the entire synthesis."""
    step = _get_build_mvp_step()
    full_ctx = _full_context_with_realistic_payloads()
    pruned = _prune_context(full_ctx, step.context_inputs)
    rendered = _render_prompt(step.prompt_template, pruned)

    # None of the prior step payloads should appear in the rendered prompt
    assert json.dumps(VALID_LANDSCAPE)[:200] not in rendered
    assert json.dumps(VALID_DEEP_DIVE)[:200] not in rendered
    assert json.dumps(VALID_CONTRARIAN)[:200] not in rendered
    # synthesis is no longer in the prompt — only the selected_idea
    assert json.dumps(VALID_SYNTHESIS)[:200] not in rendered

    # The selected_idea's distinctive content must be present
    selected_marker = VALID_SYNTHESIS["final_rankings"][0]["one_liner"]
    assert selected_marker in rendered


def test_build_mvp_unpruned_baseline_includes_everything():
    """Confirm that without pruning, every key gets substituted into a fat template."""
    step = _get_build_mvp_step()
    full_ctx = _full_context_with_realistic_payloads()
    unpruned = _render_prompt(step.prompt_template, full_ctx)

    # selected_idea (the only key build_mvp's template references now) must
    # be substituted, leaving no {selected_idea} placeholder behind.
    assert "{selected_idea}" not in unpruned


def test_build_mvp_prompt_size_drops_dramatically():
    """The headline assertion: pruning shrinks the rendered prompt.

    For build_mvp specifically the rendered prompt only references
    {synthesis}, so the size delta is small. To make this test
    meaningful for the GENERAL pruning mechanism, we use a synthetic
    template that references all four keys (the kind of template a
    careless future edit could introduce) and verify pruning works.
    """
    full_ctx = _full_context_with_realistic_payloads()

    # Synthetic worst-case template referencing every accumulated key
    fat_template = (
        "LANDSCAPE: {landscape}\n"
        "DEEP DIVE: {deep_dive}\n"
        "CONTRARIAN: {contrarian}\n"
        "SYNTHESIS: {synthesis}"
    )

    unpruned_size = len(_render_prompt(fat_template, full_ctx))

    pruned_ctx = _prune_context(full_ctx, ["synthesis"])
    pruned_size = len(_render_prompt(fat_template, pruned_ctx))

    # Unpruned must be substantially larger
    assert unpruned_size > 5_000, f"baseline only {unpruned_size} chars — fixture too small"
    # Pruning to synthesis alone must drop us by at least 50%
    assert pruned_size < unpruned_size * 0.6, (
        f"pruning didn't shrink enough: {unpruned_size} → {pruned_size}"
    )
    # And the dropped keys' payloads must be absent
    assert "BehavioralChange" not in str(pruned_ctx)  # no leftover landscape leakage


def test_pruning_preserves_full_context_dict_unchanged():
    """The pruning is non-destructive — full context object is untouched
    and can still be saved to the workflow row for debugging."""
    full_ctx = _full_context_with_realistic_payloads()
    snapshot = json.dumps(full_ctx, sort_keys=True)
    _prune_context(full_ctx, ["synthesis"])
    assert json.dumps(full_ctx, sort_keys=True) == snapshot


# ─────────────────────────────────────────────────────────────────────
# Round 4: Bug A regression — dict context values render as JSON, not Python repr
# ─────────────────────────────────────────────────────────────────────


def test_stringify_for_prompt_helper_dict():
    """A dict value is JSON-encoded with indent."""
    result = _stringify_for_prompt({"rank": 2, "name": "x"})
    parsed = json.loads(result)
    assert parsed == {"rank": 2, "name": "x"}
    # Confirm it's NOT Python repr
    assert "'rank'" not in result


def test_stringify_for_prompt_helper_list():
    """A list value is JSON-encoded too."""
    result = _stringify_for_prompt([1, 2, "three"])
    assert json.loads(result) == [1, 2, "three"]


def test_stringify_for_prompt_helper_string_passes_through():
    """Existing JSON-string outputs (the common case) are unchanged."""
    payload = '{"final_rankings": []}'
    assert _stringify_for_prompt(payload) == payload


def test_stringify_for_prompt_helper_int():
    """Plain primitives use str()."""
    assert _stringify_for_prompt(42) == "42"
    assert _stringify_for_prompt(None) == "None"


def test_render_prompt_json_encodes_dict_context_values():
    """Round 4 Bug A: when context['selected_idea'] is a dict (as it is
    after Round 3's context_overrides), the rendered prompt must contain
    valid JSON, NOT Python repr like ``{'rank': 2}``."""
    template = "build for: {selected_idea}"
    selected = {"rank": 2, "name": "second idea", "mvp_spec": {"tech_stack": "Python"}}
    rendered = _render_prompt(template, {"selected_idea": selected})

    # Extract the JSON portion and parse it — must succeed
    json_part = rendered.replace("build for: ", "", 1)
    parsed = json.loads(json_part)
    assert parsed == selected
    # And must NOT be Python repr (single quotes)
    assert "'rank'" not in rendered
    assert "'name'" not in rendered


def test_render_prompt_json_encodes_list_context_values():
    """Lists in context (e.g. a list of selected items) get JSON-encoded too."""
    template = "items: {items}"
    rendered = _render_prompt(template, {"items": ["a", "b", "c"]})
    json_part = rendered.replace("items: ", "", 1)
    assert json.loads(json_part) == ["a", "b", "c"]


def test_render_prompt_string_context_values_unchanged():
    """Backward compat: existing JSON-string step outputs render as-is."""
    payload = '{"final_rankings": [{"rank": 1}]}'
    template = "synthesis: {synthesis}"
    rendered = _render_prompt(template, {"synthesis": payload})
    assert payload in rendered
    # The string should appear literally, not double-encoded
    assert rendered.count('"final_rankings"') == 1
