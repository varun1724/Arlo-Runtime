"""Structural marker tests for the Round 1 side hustle prompt rewrite.

Each test asserts that a given prompt string contains the required
structural markers established in the SIDE_HUSTLE_IMPROVEMENTS doc.
These are guards against accidental regression of the quality bar —
if someone swaps in a simpler prompt, the marker tests fail loudly.

Tests are pure string checks, no pipeline execution. Fast to run and
don't depend on Claude or any DB.
"""

from __future__ import annotations

from app.workflows.templates import SIDE_HUSTLE_PIPELINE


def _step(name: str) -> dict:
    """Return the step dict for a given step name, or raise."""
    for s in SIDE_HUSTLE_PIPELINE["steps"]:
        if s.get("name") == name:
            return s
    raise AssertionError(f"SIDE_HUSTLE_PIPELINE has no step named {name!r}")


def _prompt(step_name: str) -> str:
    step = _step(step_name)
    return step["prompt_template"]


# ─────────────────────────────────────────────────────────────────────
# Step 0: research_side_hustles — timing taxonomy, contrarian sources,
# non-obviousness check, automation-realness check
# ─────────────────────────────────────────────────────────────────────


def test_step_0_has_timing_signal_taxonomy():
    """All 6 timing signal categories must be present, matching the
    startup pipeline's Round 1 taxonomy."""
    prompt = _prompt("research_side_hustles")
    for category in (
        "REGULATORY_SHIFT",
        "TECHNOLOGY_UNLOCK",
        "BEHAVIORAL_CHANGE",
        "COST_COLLAPSE",
        "DISTRIBUTION_UNLOCK",
        "INCUMBENT_FAILURE",
    ):
        assert category in prompt, f"missing timing category: {category}"


def test_step_0_has_contrarian_sources_list():
    """Prompt must direct Claude to contrarian sources, not just
    'passive income' blogs."""
    prompt = _prompt("research_side_hustles")
    # At least 3 of these contrarian source signals must be present
    signals = [
        "indiehackers",
        "reddit",
        "build in public",
        "show hn",
        "youtube",
        "github",
    ]
    matches = [s for s in signals if s.lower() in prompt.lower()]
    assert len(matches) >= 3, (
        f"expected at least 3 contrarian source signals, found: {matches}"
    )


def test_step_0_has_non_obviousness_check():
    """Every opportunity must be tagged with non_obviousness_check."""
    prompt = _prompt("research_side_hustles")
    assert "non_obviousness_check" in prompt
    assert "NON-OBVIOUS" in prompt or "non-obvious" in prompt


def test_step_0_has_automation_realness_check():
    """The 'fake_automation' category must exist — gurus call things
    automated that secretly need a human per item."""
    prompt = _prompt("research_side_hustles")
    assert "automation_realness_check" in prompt
    assert "fake_automation" in prompt


def test_step_0_requires_source_for_income_claims():
    """Every income claim must cite a URL, not just 'people report'."""
    prompt = _prompt("research_side_hustles")
    assert "income_evidence" in prompt
    assert "source_url" in prompt or "URL" in prompt


# ─────────────────────────────────────────────────────────────────────
# Step 1: evaluate_feasibility — score anchors, n8n node inventory,
# legal checklist
# ─────────────────────────────────────────────────────────────────────


def test_step_1_has_score_anchors_for_each_dimension():
    """All 6 dimensions must have 1/5/8/10 anchors, not arbitrary scales."""
    prompt = _prompt("evaluate_feasibility")
    assert "SCORE ANCHORS" in prompt
    for dim in (
        "revenue_potential",
        "n8n_specific_feasibility",
        "time_to_first_dollar",
        "maintenance_effort",
        "legal_safety",
        "scalability",
    ):
        assert dim in prompt, f"missing dimension: {dim}"


def test_step_1_renamed_automation_feasibility_to_n8n_specific():
    """Round 1 rename: the old 'automation_feasibility' is now
    n8n_specific_feasibility — more precise and checkable."""
    prompt = _prompt("evaluate_feasibility")
    assert "n8n_specific_feasibility" in prompt
    # The old generic name should be gone
    assert "automation_feasibility" not in prompt


def test_step_1_has_n8n_node_inventory():
    """Every opportunity must list the specific n8n nodes needed
    so the synthesis step knows whether it's really feasible."""
    prompt = _prompt("evaluate_feasibility")
    assert "n8n_node_inventory" in prompt
    # At least one availability category must be mentioned
    assert "built_in" in prompt or "community package" in prompt.lower()


def test_step_1_has_legal_checklist_with_categories():
    """The legal check must be a structured checklist with specific
    regulator names, not a generic 'legal_safety' score alone."""
    prompt = _prompt("evaluate_feasibility")
    assert "legal_checklist" in prompt
    # At least 4 of the 7 compliance categories must be named
    categories = [
        "PLATFORM_TOS",
        "CFAA",
        "FTC_AFFILIATE",
        "CAN_SPAM",
        "GDPR",
        "STATE_BUSINESS_LICENSE",
        "TAX_THRESHOLD",
    ]
    matches = [c for c in categories if c in prompt]
    assert len(matches) >= 4, (
        f"expected at least 4 legal categories, found: {matches}"
    )


# ─────────────────────────────────────────────────────────────────────
# Step 2: contrarian_analysis — named predecessors, specific evidence
# ─────────────────────────────────────────────────────────────────────


def test_step_2_requires_named_failed_predecessors():
    """No vague 'many people failed' claims — every failure must
    name the person/company."""
    prompt = _prompt("contrarian_analysis")
    assert "NAMED FAILED PREDECESSORS" in prompt
    assert "failed_predecessors" in prompt


def test_step_2_requires_specific_enforcement_evidence():
    """Platform crackdown claims must cite a specific action in the
    last 24 months, not just 'platforms can change their TOS'."""
    prompt = _prompt("contrarian_analysis")
    assert "platform_crackdown_evidence" in prompt
    assert "24 months" in prompt or "last 24" in prompt


def test_step_2_requires_saturation_with_numbers():
    """Saturation claims must cite an actual search result count."""
    prompt = _prompt("contrarian_analysis")
    assert "saturation" in prompt.lower()
    # Must direct Claude to count, not use adjectives
    assert "search result" in prompt.lower() or "approximate number" in prompt.lower()


def test_step_2_requires_primary_source_income_evidence():
    """Income reality check must prefer primary sources (screenshots,
    dashboards) over secondary (Reddit comments, gurus)."""
    prompt = _prompt("contrarian_analysis")
    assert "primary_source_links" in prompt or "primary source" in prompt.lower()
    assert "evidence_strength" in prompt
    assert "stripe" in prompt.lower() or "screenshot" in prompt.lower()


def test_step_2_has_kill_probability_field():
    """Round 1: kill_probability adds a quantitative layer to the
    qualitative verdict."""
    prompt = _prompt("contrarian_analysis")
    assert "kill_probability" in prompt
    # All three levels must be defined
    for level in ("low", "medium", "high"):
        assert level in prompt.lower()


def test_step_2_has_three_verdict_categories():
    """survives | weakened | killed — unchanged from the original
    but verified here for completeness."""
    prompt = _prompt("contrarian_analysis")
    for verdict in ("survives", "weakened", "killed"):
        assert verdict in prompt.lower()


# ─────────────────────────────────────────────────────────────────────
# Step 3: synthesis_and_ranking — weighted scoring, head-to-head,
# tightened mvp/workflow spec
# ─────────────────────────────────────────────────────────────────────


def test_step_3_uses_weighted_scoring_formula():
    """The prompt must specify the weighted scoring formula explicitly."""
    prompt = _prompt("synthesis_and_ranking")
    assert "WEIGHTED SCORING" in prompt
    # The formula must reference the weights
    assert "× 1.5" in prompt or "* 1.5" in prompt
    assert "× 0.5" in prompt or "* 0.5" in prompt


def test_step_3_has_head_to_head_comparison():
    """Round 1: each ranked entry must explain why it beats the next
    one down — forces real comparison."""
    prompt = _prompt("synthesis_and_ranking")
    assert "head_to_head" in prompt


def test_step_3_has_tightened_n8n_workflow_spec():
    """The n8n_workflow_spec must require all the fields that make
    a spec actually actionable by the build step."""
    prompt = _prompt("synthesis_and_ranking")
    required_fields = [
        "trigger_node",
        "node_graph",
        "external_credentials",
        "expected_runtime",
        "frequency",
        "out_of_scope",
        "success_metric",
        "risky_assumption",
    ]
    for field in required_fields:
        assert field in prompt, f"missing spec field: {field}"


def test_step_3_requires_webhook_trigger_not_schedule():
    """Round 4 consistency: the build step requires a webhook trigger,
    and the synthesis spec must tell Claude to specify one so the
    build prompt isn't the first place the requirement shows up."""
    prompt = _prompt("synthesis_and_ranking")
    assert "webhook" in prompt.lower()
    # Must flag that Schedule/Manual triggers don't work
    assert "schedule" in prompt.lower() or "manual" in prompt.lower()


def test_step_3_drops_killed_opportunities():
    """Only survives/weakened go into rankings — killed get dropped."""
    prompt = _prompt("synthesis_and_ranking")
    assert "survives" in prompt.lower()
    assert "killed" in prompt.lower()
    # Must explicitly say drop/exclude
    assert "drop" in prompt.lower() or "exclude" in prompt.lower()


# ─────────────────────────────────────────────────────────────────────
# Round 4 consistency: build_n8n_workflow requires webhook + settings
# ─────────────────────────────────────────────────────────────────────


def test_step_5_build_requires_webhook_trigger():
    """Round 4: the build step must tell Claude to produce a Webhook
    trigger node, not Schedule/Manual, because the test_run step
    triggers via webhook."""
    prompt = _prompt("build_n8n_workflow")
    assert "webhook" in prompt.lower()
    assert "n8n-nodes-base.webhook" in prompt


def test_step_5_build_requires_settings_field():
    """Round 4 Phase 0 finding: n8n v2.15.0 rejects workflow creation
    without a `settings` field. The build prompt must mandate it."""
    prompt = _prompt("build_n8n_workflow")
    assert "settings" in prompt.lower()


def test_step_5_build_requires_test_payload_file():
    """Round 4: the test_run step reads test_payload.json from the
    builder workspace. The build prompt must require creating it."""
    prompt = _prompt("build_n8n_workflow")
    assert "test_payload.json" in prompt


# ─────────────────────────────────────────────────────────────────────
# Sanity: step structure and output keys unchanged
# ─────────────────────────────────────────────────────────────────────


def test_pipeline_still_has_all_8_steps():
    assert len(SIDE_HUSTLE_PIPELINE["steps"]) == 8


def test_pipeline_step_names_unchanged():
    """Round 1 must NOT rename steps — downstream code references
    steps by name (e.g. the approval gate looks for 'user_picks_hustle')."""
    names = [s["name"] for s in SIDE_HUSTLE_PIPELINE["steps"]]
    assert names == [
        "research_side_hustles",
        "evaluate_feasibility",
        "contrarian_analysis",
        "synthesis_and_ranking",
        "user_picks_hustle",
        "build_n8n_workflow",
        "deploy_to_n8n",
        "test_run",
    ]


def test_pipeline_output_keys_unchanged():
    """Downstream prompts reference previous step outputs by output_key.
    Renaming an output_key silently breaks every downstream prompt."""
    keys = [s["output_key"] for s in SIDE_HUSTLE_PIPELINE["steps"]]
    assert keys == [
        "side_hustle_research",
        "feasibility",
        "contrarian",
        "synthesis",
        "_approval_placeholder",
        "build_result",
        "deploy_result",
        "test_result",
    ]


# ─────────────────────────────────────────────────────────────────────
# Round 2 schema-wiring guards
# ─────────────────────────────────────────────────────────────────────
#
# Lock in the output_schema + max_retries wiring added in Round 2 so
# a future edit can't silently drop it. If someone removes
# output_schema from a research step the research executor falls
# back to loose mode and validation stops happening — these tests
# fail loudly before that ships.


def test_research_step_has_schema_wired():
    step = _step("research_side_hustles")
    assert step.get("output_schema") == "side_hustle_research_v1"
    assert step.get("max_retries", 0) >= 2


def test_feasibility_step_has_schema_wired():
    step = _step("evaluate_feasibility")
    assert step.get("output_schema") == "side_hustle_feasibility_v1"
    assert step.get("max_retries", 0) >= 2
    # Round 2 also added context_inputs to prevent full-context bleed
    assert step.get("context_inputs") == ["side_hustle_research"]


def test_contrarian_step_has_schema_wired():
    step = _step("contrarian_analysis")
    assert step.get("output_schema") == "side_hustle_contrarian_v1"
    assert step.get("max_retries", 0) >= 2
    assert step.get("context_inputs") == ["feasibility"]


def test_synthesis_step_has_schema_wired():
    step = _step("synthesis_and_ranking")
    assert step.get("output_schema") == "side_hustle_synthesis_v1"
    assert step.get("max_retries", 0) >= 2
    # Synthesis needs all three prior outputs
    assert step.get("context_inputs") == [
        "side_hustle_research",
        "feasibility",
        "contrarian",
    ]


def test_all_research_steps_have_schemas():
    """Cross-cutting guard: every side hustle research step must have
    an output_schema. Builder and n8n steps don't need one (they're
    validated differently)."""
    for step in SIDE_HUSTLE_PIPELINE["steps"]:
        if step.get("job_type") == "research" and not step.get("requires_approval"):
            assert step.get("output_schema") is not None, (
                f"research step '{step['name']}' missing output_schema"
            )
            assert step.get("max_retries", 0) >= 1, (
                f"research step '{step['name']}' missing max_retries"
            )
