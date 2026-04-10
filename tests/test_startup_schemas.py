"""Unit tests for the Pydantic schemas in app/workflows/schemas.py.

These tests use the golden fixtures in tests/fixtures/startup_pipeline_fixtures.py
and verify that:
- VALID_* and MINIMAL_* fixtures pass validation
- INVALID_* fixtures are rejected
- The STEP_OUTPUT_SCHEMAS registry is complete and matches startup_idea_pipeline
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.workflows.schemas import (
    STEP_OUTPUT_SCHEMAS,
    ContrarianResult,
    DeepDiveResult,
    LandscapeResult,
    SynthesisResult,
    get_schema,
)
from app.workflows.templates import STARTUP_IDEA_PIPELINE
from tests.fixtures.startup_pipeline_fixtures import (
    INVALID_CONTRARIAN_BAD_KILL_PROB,
    INVALID_CONTRARIAN_BAD_VERDICT,
    INVALID_CONTRARIAN_TOO_FEW,
    INVALID_DEEP_DIVE_BAD_BILLING,
    INVALID_DEEP_DIVE_BAD_TIER,
    INVALID_DEEP_DIVE_TOO_FEW,
    INVALID_LANDSCAPE_BAD_TIMING_TYPE,
    INVALID_LANDSCAPE_FEW_OPPS,
    INVALID_LANDSCAPE_MISSING_FIELD,
    INVALID_SYNTHESIS_BAD_MOAT_RATING,
    INVALID_SYNTHESIS_EMPTY_RANKINGS,
    INVALID_SYNTHESIS_MISSING_MVP_FIELD,
    INVALID_SYNTHESIS_OUT_OF_RANGE_SCORE,
    MINIMAL_CONTRARIAN,
    MINIMAL_DEEP_DIVE,
    MINIMAL_LANDSCAPE,
    MINIMAL_SYNTHESIS,
    VALID_CONTRARIAN,
    VALID_DEEP_DIVE,
    VALID_LANDSCAPE,
    VALID_SYNTHESIS,
)


# ─────────────────────────────────────────────────────────────────────
# LandscapeResult
# ─────────────────────────────────────────────────────────────────────


def test_landscape_valid():
    result = LandscapeResult.model_validate(VALID_LANDSCAPE)
    assert len(result.opportunities) >= 5
    assert result.opportunities[0].timing_signal_type == "BEHAVIORAL_CHANGE"


def test_landscape_minimal():
    """The minimum legal landscape (5 opportunities, 1 player, 3 sources)."""
    result = LandscapeResult.model_validate(MINIMAL_LANDSCAPE)
    assert len(result.opportunities) == 5


def test_landscape_rejects_few_opportunities():
    with pytest.raises(ValidationError) as exc:
        LandscapeResult.model_validate(INVALID_LANDSCAPE_FEW_OPPS)
    assert "opportunities" in str(exc.value).lower()


def test_landscape_rejects_invalid_timing_signal_type():
    with pytest.raises(ValidationError):
        LandscapeResult.model_validate(INVALID_LANDSCAPE_BAD_TIMING_TYPE)


def test_landscape_rejects_missing_required_field():
    with pytest.raises(ValidationError) as exc:
        LandscapeResult.model_validate(INVALID_LANDSCAPE_MISSING_FIELD)
    assert "market_size" in str(exc.value)


def test_landscape_allows_extra_fields():
    """ConfigDict(extra='allow') means new prompt fields don't break validation."""
    payload = {**MINIMAL_LANDSCAPE, "future_field": "some new thing"}
    result = LandscapeResult.model_validate(payload)
    # Extra field is preserved on dump
    assert result.model_dump()["future_field"] == "some new thing"


# ─────────────────────────────────────────────────────────────────────
# DeepDiveResult
# ─────────────────────────────────────────────────────────────────────


def test_deep_dive_valid():
    result = DeepDiveResult.model_validate(VALID_DEEP_DIVE)
    assert len(result.deep_dive_opportunities) >= 3
    first = result.deep_dive_opportunities[0]
    assert first.unit_economics.billing_model in {
        "subscription", "usage", "one_time", "freemium", "marketplace_take"
    }
    assert any(s.tier == "HOT" for s in first.demand_signals)


def test_deep_dive_minimal():
    result = DeepDiveResult.model_validate(MINIMAL_DEEP_DIVE)
    assert len(result.deep_dive_opportunities) == 3


def test_deep_dive_rejects_too_few_opportunities():
    with pytest.raises(ValidationError):
        DeepDiveResult.model_validate(INVALID_DEEP_DIVE_TOO_FEW)


def test_deep_dive_rejects_invalid_demand_tier():
    with pytest.raises(ValidationError):
        DeepDiveResult.model_validate(INVALID_DEEP_DIVE_BAD_TIER)


def test_deep_dive_rejects_invalid_billing_model():
    with pytest.raises(ValidationError):
        DeepDiveResult.model_validate(INVALID_DEEP_DIVE_BAD_BILLING)


def test_deep_dive_unit_economics_required():
    """unit_economics block is required and shaped."""
    result = DeepDiveResult.model_validate(VALID_DEEP_DIVE)
    for opp in result.deep_dive_opportunities:
        assert opp.unit_economics is not None
        assert opp.unit_economics.gross_margin_signal in {"high", "medium", "low"}


# ─────────────────────────────────────────────────────────────────────
# ContrarianResult
# ─────────────────────────────────────────────────────────────────────


def test_contrarian_valid():
    result = ContrarianResult.model_validate(VALID_CONTRARIAN)
    assert len(result.contrarian_analyses) >= 3
    verdicts = {a.verdict for a in result.contrarian_analyses}
    assert verdicts.issubset({"survives", "weakened", "killed"})


def test_contrarian_minimal():
    result = ContrarianResult.model_validate(MINIMAL_CONTRARIAN)
    assert len(result.contrarian_analyses) == 3


def test_contrarian_rejects_too_few():
    with pytest.raises(ValidationError):
        ContrarianResult.model_validate(INVALID_CONTRARIAN_TOO_FEW)


def test_contrarian_rejects_invalid_verdict():
    with pytest.raises(ValidationError):
        ContrarianResult.model_validate(INVALID_CONTRARIAN_BAD_VERDICT)


def test_contrarian_rejects_invalid_kill_probability():
    with pytest.raises(ValidationError):
        ContrarianResult.model_validate(INVALID_CONTRARIAN_BAD_KILL_PROB)


def test_contrarian_regulatory_risk_block_required():
    result = ContrarianResult.model_validate(VALID_CONTRARIAN)
    for analysis in result.contrarian_analyses:
        assert analysis.regulatory_risk is not None
        assert analysis.regulatory_risk.compliance_burden in {"low", "medium", "high"}


# ─────────────────────────────────────────────────────────────────────
# SynthesisResult
# ─────────────────────────────────────────────────────────────────────


def test_synthesis_valid():
    result = SynthesisResult.model_validate(VALID_SYNTHESIS)
    assert len(result.final_rankings) >= 1
    top = result.final_rankings[0]
    assert top.rank == 1
    assert top.mvp_spec.risky_assumption  # required
    assert top.mvp_spec.out_of_scope  # required, min_length=1
    assert top.head_to_head  # comparative field present


def test_synthesis_minimal():
    """Round 3: minimum legal synthesis is 3 rankings (was 1 in Round 2)."""
    result = SynthesisResult.model_validate(MINIMAL_SYNTHESIS)
    assert len(result.final_rankings) == 3


def test_synthesis_rejects_empty_rankings():
    """The 'all ideas killed' silent failure case — must be loud."""
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_EMPTY_RANKINGS)
    assert "final_rankings" in str(exc.value)


def test_synthesis_rejects_too_few_rankings():
    """Round 3: 2 rankings is below the min_length=3 floor."""
    from tests.fixtures.startup_pipeline_fixtures import INVALID_SYNTHESIS_TOO_FEW_RANKINGS
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_TOO_FEW_RANKINGS)
    assert "final_rankings" in str(exc.value)


def test_synthesis_rejects_low_total_score():
    """Round 3: total_score < 20 means Claude couldn't find a real opportunity."""
    from tests.fixtures.startup_pipeline_fixtures import INVALID_SYNTHESIS_LOW_TOTAL_SCORE
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_LOW_TOTAL_SCORE)
    assert "total_score" in str(exc.value)


def test_synthesis_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        SynthesisResult.model_validate(INVALID_SYNTHESIS_OUT_OF_RANGE_SCORE)


def test_synthesis_rejects_missing_mvp_field():
    """risky_assumption is required — building without it leads to scope creep."""
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_MISSING_MVP_FIELD)
    assert "risky_assumption" in str(exc.value)


def test_synthesis_rejects_short_risky_assumption():
    """Round 3: risky_assumption needs at least 15 chars to be useful."""
    from tests.fixtures.startup_pipeline_fixtures import INVALID_SYNTHESIS_SHORT_RISKY_ASSUMPTION
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_SHORT_RISKY_ASSUMPTION)
    assert "risky_assumption" in str(exc.value)


def test_synthesis_rejects_short_core_user_journey():
    """Round 3: core_user_journey needs at least 20 chars."""
    from tests.fixtures.startup_pipeline_fixtures import INVALID_SYNTHESIS_SHORT_CORE_USER_JOURNEY
    with pytest.raises(ValidationError) as exc:
        SynthesisResult.model_validate(INVALID_SYNTHESIS_SHORT_CORE_USER_JOURNEY)
    assert "core_user_journey" in str(exc.value)


def test_synthesis_rejects_bad_moat_rating():
    with pytest.raises(ValidationError):
        SynthesisResult.model_validate(INVALID_SYNTHESIS_BAD_MOAT_RATING)


def test_synthesis_moats_taxonomy_complete():
    """All 5 moat dimensions required."""
    result = SynthesisResult.model_validate(VALID_SYNTHESIS)
    moats = result.final_rankings[0].moats
    assert moats.network_effects is not None
    assert moats.switching_costs is not None
    assert moats.data_advantage is not None
    assert moats.brand_or_trust is not None
    assert moats.distribution_lock is not None


# ─────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────


def test_registry_lookup():
    assert get_schema("startup_landscape_v1") is LandscapeResult
    assert get_schema("startup_deep_dive_v1") is DeepDiveResult
    assert get_schema("startup_contrarian_v1") is ContrarianResult
    assert get_schema("startup_synthesis_v1") is SynthesisResult


def test_registry_get_unknown_returns_none():
    assert get_schema("does_not_exist") is None
    assert get_schema(None) is None


def test_registry_completeness():
    """Every step in startup_idea_pipeline that names an output_schema must
    have a registry entry — otherwise the lookup at runtime returns None
    and validation silently degrades to loose mode."""
    for step in STARTUP_IDEA_PIPELINE["steps"]:
        schema_name = step.get("output_schema")
        if schema_name is not None:
            assert schema_name in STEP_OUTPUT_SCHEMAS, (
                f"Step '{step['name']}' references missing schema '{schema_name}'"
            )


def test_registry_round_trip_normalizes():
    """model_dump_json() output is parseable by the same schema."""
    original = LandscapeResult.model_validate(VALID_LANDSCAPE)
    dumped = original.model_dump_json()
    reparsed = LandscapeResult.model_validate_json(dumped)
    assert reparsed == original
