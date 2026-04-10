"""Tests for the Round 5 deep_research_mode flag.

Pure unit tests for the ``_apply_deep_research_mode`` helper + sanity
checks that the prompts reference the ``{deep_mode}`` placeholder so
the context gets substituted properly at render time.
"""

from __future__ import annotations

from app.workflows.templates import (
    STARTUP_IDEA_PIPELINE,
    _apply_deep_research_mode,
)


def test_apply_bumps_contrarian_max_loop_count():
    """Deep mode bumps contrarian's max_loop_count from 2 to 4."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    contrarian = next(s for s in steps if s["name"] == "contrarian_analysis")
    assert contrarian["max_loop_count"] == 4


def test_apply_bumps_landscape_timeout():
    """Deep mode bumps landscape_scan timeout_override to 1800s."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    landscape = next(s for s in steps if s["name"] == "landscape_scan")
    assert landscape["timeout_override"] == 1800


def test_apply_adds_deep_mode_to_context():
    """Deep mode injects ``deep_mode="true"`` as a string into initial_context."""
    _, context = _apply_deep_research_mode(
        STARTUP_IDEA_PIPELINE["steps"],
        {"domain": "AI tools", "focus_areas": "code review"},
    )
    assert context["deep_mode"] == "true"
    # Existing keys preserved
    assert context["domain"] == "AI tools"
    assert context["focus_areas"] == "code review"


def test_apply_does_not_mutate_original_steps():
    """The helper must use a deep copy so the module-level template
    is never modified."""
    original_contrarian = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "contrarian_analysis"
    )
    original_max = original_contrarian["max_loop_count"]
    original_ls = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "landscape_scan"
    )
    original_timeout = original_ls["timeout_override"]

    _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})

    # Originals untouched
    assert original_contrarian["max_loop_count"] == original_max
    assert original_ls["timeout_override"] == original_timeout


def test_apply_does_not_mutate_original_context():
    """The input context dict should not be modified in place."""
    original_context = {"domain": "x", "focus_areas": "y"}
    snapshot = dict(original_context)
    _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], original_context)
    assert original_context == snapshot


def test_apply_is_safe_on_unknown_template():
    """Applying the helper to a pipeline without landscape_scan or
    contrarian_analysis should still work (noop-ish) and return a
    valid (steps, context) tuple."""
    dummy_steps = [
        {"name": "other_step", "job_type": "research", "prompt_template": "x", "output_key": "y"},
    ]
    steps, context = _apply_deep_research_mode(dummy_steps, {"domain": "test"})
    assert len(steps) == 1
    assert steps[0]["name"] == "other_step"
    # deep_mode is still added to context
    assert context["deep_mode"] == "true"


def test_landscape_prompt_references_deep_mode_placeholder():
    """The landscape prompt must contain {deep_mode} so the context
    substitution actually happens at render time."""
    landscape = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "landscape_scan"
    )
    assert "{deep_mode}" in landscape["prompt_template"]
    assert "DEEP RESEARCH MODE" in landscape["prompt_template"]


def test_deep_dive_prompt_references_deep_mode_placeholder():
    deep_dive = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "deep_dive"
    )
    assert "{deep_mode}" in deep_dive["prompt_template"]


def test_synthesis_prompt_references_deep_mode_placeholder():
    synthesis = next(
        s for s in STARTUP_IDEA_PIPELINE["steps"] if s["name"] == "synthesis_and_ranking"
    )
    assert "{deep_mode}" in synthesis["prompt_template"]


def test_default_request_has_deep_research_mode_false():
    """The flag is opt-in: default is False."""
    from app.models.workflow import CreateWorkflowFromTemplateRequest

    req = CreateWorkflowFromTemplateRequest(initial_context={"domain": "x"})
    assert req.deep_research_mode is False


def test_request_accepts_deep_research_mode_true():
    from app.models.workflow import CreateWorkflowFromTemplateRequest

    req = CreateWorkflowFromTemplateRequest(
        initial_context={"domain": "x"},
        deep_research_mode=True,
    )
    assert req.deep_research_mode is True
