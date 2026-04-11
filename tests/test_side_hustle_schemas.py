"""Unit tests for the Round 2 side hustle Pydantic schemas.

Mirrors tests/test_startup_schemas.py. Covers:
- Happy-path validation for each of the 4 schemas
- Minimal-legal validation (smallest JSON that satisfies all constraints)
- Rejection on min_length violation
- Rejection on missing required field
- Rejection on bad enum value
- Cross-cutting: extra-field tolerance, round-trip serialization,
  registry completeness

All tests are pure unit — no Claude, no DB, no network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.workflows.schemas import (
    STEP_OUTPUT_SCHEMAS,
    SideHustleContrarianResult,
    SideHustleFeasibilityResult,
    SideHustleResearchResult,
    SideHustleSynthesisResult,
)
from app.workflows.templates import SIDE_HUSTLE_PIPELINE
from tests.fixtures.side_hustle_fixtures import (
    INVALID_CONTRARIAN_BAD_KILL_PROB,
    INVALID_CONTRARIAN_BAD_VERDICT,
    INVALID_CONTRARIAN_FEW_ANALYSES,
    INVALID_FEASIBILITY_BAD_LEGAL_CATEGORY,
    INVALID_FEASIBILITY_BAD_SCORE,
    INVALID_FEASIBILITY_FEW_EVALS,
    INVALID_RESEARCH_BAD_TIMING_TYPE,
    INVALID_RESEARCH_FEW_OPPS,
    INVALID_RESEARCH_MISSING_FIELD,
    INVALID_SYNTHESIS_FEW_RANKINGS,
    INVALID_SYNTHESIS_SPEC_MISSING_FIELD,
    INVALID_SYNTHESIS_SPEC_WRONG_OUT_OF_SCOPE_COUNT,
    MINIMAL_SIDE_HUSTLE_CONTRARIAN,
    MINIMAL_SIDE_HUSTLE_FEASIBILITY,
    MINIMAL_SIDE_HUSTLE_RESEARCH,
    MINIMAL_SIDE_HUSTLE_SYNTHESIS,
    VALID_SIDE_HUSTLE_CONTRARIAN,
    VALID_SIDE_HUSTLE_FEASIBILITY,
    VALID_SIDE_HUSTLE_RESEARCH,
    VALID_SIDE_HUSTLE_SYNTHESIS,
)


# ─────────────────────────────────────────────────────────────────────
# Research schema
# ─────────────────────────────────────────────────────────────────────


def test_research_valid():
    result = SideHustleResearchResult.model_validate(VALID_SIDE_HUSTLE_RESEARCH)
    assert len(result.opportunities) >= 8
    assert len(result.sources_consulted) >= 3


def test_research_minimal():
    result = SideHustleResearchResult.model_validate(MINIMAL_SIDE_HUSTLE_RESEARCH)
    assert len(result.opportunities) == 8


def test_research_rejects_few_opportunities():
    with pytest.raises(ValidationError) as exc:
        SideHustleResearchResult.model_validate(INVALID_RESEARCH_FEW_OPPS)
    assert "opportunities" in str(exc.value).lower()


def test_research_rejects_missing_field():
    with pytest.raises(ValidationError) as exc:
        SideHustleResearchResult.model_validate(INVALID_RESEARCH_MISSING_FIELD)
    assert "income_evidence" in str(exc.value)


def test_research_rejects_bad_timing_signal_type():
    with pytest.raises(ValidationError) as exc:
        SideHustleResearchResult.model_validate(INVALID_RESEARCH_BAD_TIMING_TYPE)
    assert "timing_signal_type" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Feasibility schema
# ─────────────────────────────────────────────────────────────────────


def test_feasibility_valid():
    result = SideHustleFeasibilityResult.model_validate(VALID_SIDE_HUSTLE_FEASIBILITY)
    assert len(result.evaluations) >= 5


def test_feasibility_minimal():
    result = SideHustleFeasibilityResult.model_validate(MINIMAL_SIDE_HUSTLE_FEASIBILITY)
    assert len(result.evaluations) == 5


def test_feasibility_rejects_few_evaluations():
    with pytest.raises(ValidationError) as exc:
        SideHustleFeasibilityResult.model_validate(INVALID_FEASIBILITY_FEW_EVALS)
    assert "evaluations" in str(exc.value).lower()


def test_feasibility_rejects_score_out_of_range():
    """revenue_potential=11 should be rejected by Field(ge=1, le=10)."""
    with pytest.raises(ValidationError) as exc:
        SideHustleFeasibilityResult.model_validate(INVALID_FEASIBILITY_BAD_SCORE)
    assert "revenue_potential" in str(exc.value)


def test_feasibility_rejects_bad_legal_category():
    with pytest.raises(ValidationError) as exc:
        SideHustleFeasibilityResult.model_validate(INVALID_FEASIBILITY_BAD_LEGAL_CATEGORY)
    assert "compliance_categories" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Contrarian schema
# ─────────────────────────────────────────────────────────────────────


def test_contrarian_valid():
    result = SideHustleContrarianResult.model_validate(VALID_SIDE_HUSTLE_CONTRARIAN)
    assert len(result.analyses) >= 5
    assert result.summary


def test_contrarian_minimal():
    result = SideHustleContrarianResult.model_validate(MINIMAL_SIDE_HUSTLE_CONTRARIAN)
    assert len(result.analyses) == 5


def test_contrarian_rejects_few_analyses():
    with pytest.raises(ValidationError) as exc:
        SideHustleContrarianResult.model_validate(INVALID_CONTRARIAN_FEW_ANALYSES)
    assert "analyses" in str(exc.value).lower()


def test_contrarian_rejects_bad_verdict():
    with pytest.raises(ValidationError) as exc:
        SideHustleContrarianResult.model_validate(INVALID_CONTRARIAN_BAD_VERDICT)
    assert "verdict" in str(exc.value).lower()


def test_contrarian_rejects_bad_kill_probability():
    with pytest.raises(ValidationError) as exc:
        SideHustleContrarianResult.model_validate(INVALID_CONTRARIAN_BAD_KILL_PROB)
    assert "kill_probability" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Synthesis schema
# ─────────────────────────────────────────────────────────────────────


def test_synthesis_valid():
    result = SideHustleSynthesisResult.model_validate(VALID_SIDE_HUSTLE_SYNTHESIS)
    assert len(result.final_rankings) >= 2
    assert result.final_rankings[0].rank == 1


def test_synthesis_minimal():
    result = SideHustleSynthesisResult.model_validate(MINIMAL_SIDE_HUSTLE_SYNTHESIS)
    assert len(result.final_rankings) == 2


def test_synthesis_rejects_few_rankings():
    with pytest.raises(ValidationError) as exc:
        SideHustleSynthesisResult.model_validate(INVALID_SYNTHESIS_FEW_RANKINGS)
    assert "final_rankings" in str(exc.value).lower()


def test_synthesis_rejects_spec_missing_required_field():
    with pytest.raises(ValidationError) as exc:
        SideHustleSynthesisResult.model_validate(INVALID_SYNTHESIS_SPEC_MISSING_FIELD)
    assert "risky_assumption" in str(exc.value)


def test_synthesis_rejects_wrong_out_of_scope_count():
    """Round 1 rule: out_of_scope must have exactly 3 items."""
    with pytest.raises(ValidationError) as exc:
        SideHustleSynthesisResult.model_validate(
            INVALID_SYNTHESIS_SPEC_WRONG_OUT_OF_SCOPE_COUNT
        )
    assert "out_of_scope" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────
# Cross-cutting
# ─────────────────────────────────────────────────────────────────────


def test_all_side_hustle_schemas_allow_extra_fields():
    """ConfigDict(extra='allow') means prompt field additions don't
    break in-flight workflows."""
    payload = {
        **MINIMAL_SIDE_HUSTLE_RESEARCH,
        "future_field_added_by_a_later_prompt_revision": "some value",
    }
    result = SideHustleResearchResult.model_validate(payload)
    dumped = result.model_dump()
    assert dumped["future_field_added_by_a_later_prompt_revision"] == "some value"


def test_all_side_hustle_schemas_round_trip_via_json():
    """model_dump_json() output must be parseable by the same schema."""
    pairs = [
        (SideHustleResearchResult, VALID_SIDE_HUSTLE_RESEARCH),
        (SideHustleFeasibilityResult, VALID_SIDE_HUSTLE_FEASIBILITY),
        (SideHustleContrarianResult, VALID_SIDE_HUSTLE_CONTRARIAN),
        (SideHustleSynthesisResult, VALID_SIDE_HUSTLE_SYNTHESIS),
    ]
    for schema_cls, payload in pairs:
        original = schema_cls.model_validate(payload)
        dumped = original.model_dump_json()
        reparsed = schema_cls.model_validate_json(dumped)
        assert reparsed == original, f"round-trip failed for {schema_cls.__name__}"


def test_registry_has_all_side_hustle_schemas():
    """Every side hustle step that names an output_schema must have a
    registry entry — otherwise the runtime lookup returns None and
    validation silently degrades to loose mode."""
    expected = {
        "side_hustle_research_v1",
        "side_hustle_feasibility_v1",
        "side_hustle_contrarian_v1",
        "side_hustle_synthesis_v1",
    }
    for name in expected:
        assert name in STEP_OUTPUT_SCHEMAS, f"missing registry entry: {name}"


def test_side_hustle_pipeline_steps_all_have_registered_schemas():
    """Registry completeness check scoped to the side hustle pipeline
    specifically: every step that sets output_schema must point at a
    real registered schema."""
    for step in SIDE_HUSTLE_PIPELINE["steps"]:
        schema_name = step.get("output_schema")
        if schema_name is not None:
            assert schema_name in STEP_OUTPUT_SCHEMAS, (
                f"step '{step['name']}' references missing schema '{schema_name}'"
            )
