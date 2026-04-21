"""Tests for the Round 5 deep_research_mode flag.

Pure unit tests for the ``_apply_deep_research_mode`` helper + sanity
checks that the prompts reference the ``{deep_mode}`` placeholder so
the context gets substituted properly at render time.
"""

from __future__ import annotations

from app.workflows.templates import (
    SIDE_HUSTLE_PIPELINE,
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


def test_apply_bumps_contrarian_timeout():
    """Round 5.5: deep mode bumps contrarian timeout from 1800s to 2700s.
    Real production run hit the old 30-min wall mid-search."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    contrarian = next(s for s in steps if s["name"] == "contrarian_analysis")
    assert contrarian["timeout_override"] == 2700


def test_apply_bumps_deep_dive_timeout():
    """Round 5.6: deep mode bumps deep_dive timeout from 1800s to 2700s.
    Second real deep-mode run hit the old 30-min wall in deep_dive."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    deep_dive = next(s for s in steps if s["name"] == "deep_dive")
    assert deep_dive["timeout_override"] == 2700


def test_apply_bumps_synthesis_timeout():
    """Round 5.5: deep mode bumps synthesis timeout from 1200s to 1800s
    because there are more opportunities to rank."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    synthesis = next(s for s in steps if s["name"] == "synthesis_and_ranking")
    assert synthesis["timeout_override"] == 1800


def test_apply_bumps_freshness_check_timeout():
    """Batch B: deep mode bumps freshness_check timeout to 1500s because
    more survivors → more per-opportunity 30-day news queries."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    freshness = next(s for s in steps if s["name"] == "freshness_check")
    assert freshness["timeout_override"] == 1500


def test_apply_bumps_validation_plan_timeout():
    """Batch B: deep mode bumps validation_plan timeout to 1200s because
    deep mode ranks more opps → more plans to produce."""
    steps, _ = _apply_deep_research_mode(STARTUP_IDEA_PIPELINE["steps"], {})
    validation = next(s for s in steps if s["name"] == "validation_plan")
    assert validation["timeout_override"] == 1200


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


# ─────────────────────────────────────────────────────────────────────
# Round 6.B1/B2/B3: side hustle pipeline deep research mode parity
# ─────────────────────────────────────────────────────────────────────


def test_apply_deep_mode_bumps_side_hustle_research_timeout():
    """Round 6.B1: research_side_hustles gets 2400s in deep mode
    (was 1800s) so the broader 15-20-opportunity search has headroom."""
    steps, _ = _apply_deep_research_mode(SIDE_HUSTLE_PIPELINE["steps"], {})
    research = next(s for s in steps if s["name"] == "research_side_hustles")
    assert research["timeout_override"] == 2400


def test_apply_deep_mode_bumps_side_hustle_feasibility_timeout():
    """Round 6.B1: evaluate_feasibility gets 2700s in deep mode
    (was 1800s) — same proportional bump as deep_dive on the
    startup pipeline."""
    steps, _ = _apply_deep_research_mode(SIDE_HUSTLE_PIPELINE["steps"], {})
    feasibility = next(s for s in steps if s["name"] == "evaluate_feasibility")
    assert feasibility["timeout_override"] == 2700


def test_apply_deep_mode_still_bumps_contrarian_for_side_hustle():
    """Round 6.B1 regression guard: contrarian_analysis bump still
    fires for the side hustle template (same step name as startup,
    so the shared branch should match)."""
    steps, _ = _apply_deep_research_mode(SIDE_HUSTLE_PIPELINE["steps"], {})
    contrarian = next(s for s in steps if s["name"] == "contrarian_analysis")
    assert contrarian["max_loop_count"] == 4
    assert contrarian["timeout_override"] == 2700


def test_side_hustle_prompts_contain_deep_mode_placeholders():
    """Round 6.B2: each of the 4 side hustle research prompts must
    reference {deep_mode} so the context substitution actually fires
    at render time, AND must contain a DEEP RESEARCH MODE instruction
    block so Claude knows what to do when the flag is true."""
    research_step_names = (
        "research_side_hustles",
        "evaluate_feasibility",
        "contrarian_analysis",
        "synthesis_and_ranking",
    )
    for name in research_step_names:
        step = next(
            s for s in SIDE_HUSTLE_PIPELINE["steps"] if s["name"] == name
        )
        assert "{deep_mode}" in step["prompt_template"], (
            f"Round 6.B2: {name} prompt missing {{deep_mode}} placeholder"
        )
        assert "DEEP RESEARCH MODE" in step["prompt_template"], (
            f"Round 6.B2: {name} prompt missing DEEP RESEARCH MODE block"
        )


# ─────────────────────────────────────────────────────────────────────
# Round 6 followup: n8n activation validation loop template assertions
# ─────────────────────────────────────────────────────────────────────


from app.workflows.templates import FREELANCE_SCANNER_PIPELINE  # noqa: E402


def _get_step(pipeline, name):
    return next(s for s in pipeline["steps"] if s["name"] == name)


def test_side_hustle_deploy_has_activation_loop():
    """deploy_to_n8n must have loop_to pointing at build_n8n_workflow
    (step index 5) with a 'contains activation_error' condition."""
    step = _get_step(SIDE_HUSTLE_PIPELINE, "deploy_to_n8n")
    assert step.get("loop_to") == 5
    assert step.get("max_loop_count") == 3
    cond = step.get("loop_condition", {})
    assert cond.get("field") == "deploy_result"
    assert cond.get("operator") == "contains"
    assert cond.get("value") == "activation_error"


def test_side_hustle_build_has_deploy_result_in_context_inputs():
    """build_n8n_workflow must include deploy_result in context_inputs
    so the activation error from a failed deploy is available in the
    prompt on a retry iteration."""
    step = _get_step(SIDE_HUSTLE_PIPELINE, "build_n8n_workflow")
    assert "deploy_result" in step.get("context_inputs", [])
    assert "{deploy_result}" in step["prompt_template"]


def test_freelance_scanner_deploy_has_activation_loop():
    """deploy_scanner must have the same activation loop pattern."""
    step = _get_step(FREELANCE_SCANNER_PIPELINE, "deploy_scanner")
    assert step.get("loop_to") == 5
    assert step.get("max_loop_count") == 3
    cond = step.get("loop_condition", {})
    assert cond.get("field") == "deploy_result"
    assert cond.get("operator") == "contains"
    assert cond.get("value") == "activation_error"


def test_freelance_scanner_build_has_deploy_result_in_context():
    """build_scanner_workflow must include deploy_result for error
    feedback, same as the side hustle pipeline."""
    step = _get_step(FREELANCE_SCANNER_PIPELINE, "build_scanner_workflow")
    assert "deploy_result" in step.get("context_inputs", [])
    assert "{deploy_result}" in step["prompt_template"]


def test_freelance_scanner_deploy_uses_from_previous_build():
    """deploy_scanner must use from_previous_build (not the old-style
    {build_result} interpolation that corrupts on quotes/backslashes)."""
    step = _get_step(FREELANCE_SCANNER_PIPELINE, "deploy_scanner")
    assert "from_previous_build" in step["prompt_template"]
    assert "{build_result}" not in step["prompt_template"]
