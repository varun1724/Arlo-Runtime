"""Tests for the validation/normalization path in app/jobs/research.py.

These tests cover ``_extract_result`` directly. They do NOT exercise the
full ``execute_research_job`` workflow because that requires a real
database session — the relevant integration is covered by
``test_workflow_retry.py`` (which exercises ``advance_workflow``'s
retry path) and the live end-to-end run after deployment.

The function under test has three modes:

1. **Strict workflow mode** (raw_mode=True, schema_cls set): valid JSON
   that matches the schema is normalized; invalid JSON or schema
   mismatches raise ClaudeRunError.
2. **Loose workflow mode** (raw_mode=True, schema_cls=None): legacy
   behavior; invalid JSON falls back to storing the raw string.
3. **Standalone mode** (raw_mode=False): validates against ResearchReport.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.jobs.research import _extract_result
from app.services.claude_runner import ClaudeRunError
from app.workflows.schemas import LandscapeResult, SynthesisResult
from tests.fixtures.startup_pipeline_fixtures import (
    INVALID_LANDSCAPE_FEW_OPPS,
    INVALID_SYNTHESIS_EMPTY_RANKINGS,
    INVALID_SYNTHESIS_MISSING_MVP_FIELD,
    MINIMAL_LANDSCAPE,
    MINIMAL_SYNTHESIS,
    VALID_LANDSCAPE,
    VALID_SYNTHESIS,
)


def _claude_output(payload) -> dict:
    """Wrap a Python value the way the Claude CLI subprocess result is shaped."""
    if isinstance(payload, str):
        return {"result": payload}
    return {"result": json.dumps(payload)}


# ─────────────────────────────────────────────────────────────────────
# Strict workflow mode (raw_mode=True, schema_cls set)
# ─────────────────────────────────────────────────────────────────────


def test_strict_mode_valid_payload_returns_normalized_json():
    output = _claude_output(VALID_LANDSCAPE)
    result_json, preview = _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)

    parsed = json.loads(result_json)
    # Normalized JSON validates again
    LandscapeResult.model_validate(parsed)
    assert preview  # non-empty preview built


def test_strict_mode_minimal_payload_passes():
    output = _claude_output(MINIMAL_LANDSCAPE)
    result_json, _preview = _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    parsed = json.loads(result_json)
    assert len(parsed["opportunities"]) == 5


def test_strict_mode_schema_mismatch_raises():
    """Schema validation failure must raise ClaudeRunError to trigger retry."""
    output = _claude_output(INVALID_LANDSCAPE_FEW_OPPS)
    with pytest.raises(ClaudeRunError) as exc:
        _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    assert "validation failed" in str(exc.value).lower()
    assert "LandscapeResult" in str(exc.value)


def test_strict_mode_invalid_json_raises():
    """Bad JSON in strict mode must raise — never fall back to raw storage."""
    output = {"result": "this is not JSON at all"}
    with pytest.raises(ClaudeRunError) as exc:
        _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    assert "not valid JSON" in str(exc.value)


def test_strict_mode_empty_synthesis_raises():
    """The 'all ideas killed' silent-failure case is now loud."""
    output = _claude_output(INVALID_SYNTHESIS_EMPTY_RANKINGS)
    with pytest.raises(ClaudeRunError):
        _extract_result(output, raw_mode=True, schema_cls=SynthesisResult)


def test_strict_mode_missing_mvp_field_raises():
    output = _claude_output(INVALID_SYNTHESIS_MISSING_MVP_FIELD)
    with pytest.raises(ClaudeRunError) as exc:
        _extract_result(output, raw_mode=True, schema_cls=SynthesisResult)
    assert "risky_assumption" in str(exc.value)


def test_strict_mode_strips_markdown_fences_then_validates():
    """Claude often wraps JSON in ```json fences. Existing stripping must stay."""
    fenced = "```json\n" + json.dumps(MINIMAL_LANDSCAPE) + "\n```"
    output = {"result": fenced}
    result_json, _ = _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    parsed = json.loads(result_json)
    LandscapeResult.model_validate(parsed)


def test_strict_mode_preserves_extra_fields_in_dump():
    """ConfigDict(extra='allow') should preserve unknown fields through validation."""
    payload = {**MINIMAL_LANDSCAPE, "future_field": "preserved"}
    output = _claude_output(payload)
    result_json, _ = _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    parsed = json.loads(result_json)
    assert parsed.get("future_field") == "preserved"


def test_strict_mode_synthesis_round_trip():
    """A valid synthesis goes in, normalized synthesis comes out, re-validates."""
    output = _claude_output(VALID_SYNTHESIS)
    result_json, _ = _extract_result(output, raw_mode=True, schema_cls=SynthesisResult)
    parsed = json.loads(result_json)
    SynthesisResult.model_validate(parsed)


# ─────────────────────────────────────────────────────────────────────
# Loose workflow mode (backward compat, schema_cls=None)
# ─────────────────────────────────────────────────────────────────────


def test_loose_mode_valid_json_passes_through():
    payload = {"any_shape": "is fine", "no_validation": True}
    output = _claude_output(payload)
    result_json, preview = _extract_result(output, raw_mode=True, schema_cls=None)
    assert json.loads(result_json) == payload
    assert preview


def test_loose_mode_invalid_json_falls_back_to_raw_string():
    """Backward compat: legacy templates still tolerate raw-string fallback."""
    output = {"result": "definitely not json"}
    result_json, preview = _extract_result(output, raw_mode=True, schema_cls=None)
    assert result_json == "definitely not json"
    assert preview == "definitely not json"


def test_loose_mode_no_schema_no_validation():
    """A payload that would fail strict mode passes loose mode."""
    output = _claude_output(INVALID_LANDSCAPE_FEW_OPPS)
    result_json, _ = _extract_result(output, raw_mode=True, schema_cls=None)
    parsed = json.loads(result_json)
    assert len(parsed["opportunities"]) == 4  # not enough for strict, but accepted


# ─────────────────────────────────────────────────────────────────────
# Standalone mode (raw_mode=False, validates ResearchReport)
# ─────────────────────────────────────────────────────────────────────


def _valid_research_report() -> dict:
    return {
        "market_overview": "x",
        "opportunities": [
            {
                "name": "n",
                "description": "d",
                "evidence": ["e1", "e2"],
                "market_size_estimate": "1B",
                "competition_level": "low",
                "feasibility": "high",
            }
        ],
        "trends": ["t1"],
        "risks": ["r1"],
        "top_recommendations": [{"name": "n", "reasoning": "r"}],
    }


def test_standalone_mode_valid_research_report():
    output = _claude_output(_valid_research_report())
    result_json, preview = _extract_result(output, raw_mode=False, schema_cls=None)
    parsed = json.loads(result_json)
    assert parsed["market_overview"] == "x"
    assert preview


def test_standalone_mode_invalid_report_raises():
    output = _claude_output({"market_overview": "missing other fields"})
    with pytest.raises(ClaudeRunError) as exc:
        _extract_result(output, raw_mode=False, schema_cls=None)
    assert "ResearchReport" in str(exc.value)


def test_standalone_mode_invalid_json_raises():
    output = {"result": "not json"}
    with pytest.raises(ClaudeRunError):
        _extract_result(output, raw_mode=False, schema_cls=None)


# ─────────────────────────────────────────────────────────────────────
# Round 3: friendly validation error helper
# ─────────────────────────────────────────────────────────────────────


def test_friendly_error_includes_field_name():
    """Round 3: ClaudeRunError messages should name the offending field."""
    output = _claude_output(INVALID_LANDSCAPE_FEW_OPPS)
    with pytest.raises(ClaudeRunError) as exc:
        _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
    # The friendly error should reference the failing field by name
    assert "opportunities" in str(exc.value)
    # And the schema class name (so the user knows which step failed)
    assert "LandscapeResult" in str(exc.value)


def test_friendly_error_is_short_one_liner():
    """Round 3: friendly error is much shorter than raw Pydantic output."""
    output = _claude_output(INVALID_LANDSCAPE_FEW_OPPS)
    try:
        _extract_result(output, raw_mode=True, schema_cls=LandscapeResult)
        assert False, "should have raised"
    except ClaudeRunError as e:
        msg = str(e)
        # Should be one line and well under the wall-of-text Pydantic default
        assert "\n" not in msg
        assert len(msg) < 300


def test_friendly_error_includes_more_count_when_multiple_failures():
    """When multiple fields fail, the helper notes the additional count."""
    from app.jobs.research import _friendly_validation_error
    from pydantic import BaseModel, Field

    class Sample(BaseModel):
        a: int = Field(ge=10)
        b: int = Field(ge=10)

    try:
        Sample.model_validate({"a": 1, "b": 1})
        assert False, "should have raised"
    except ValidationError as e:
        msg = _friendly_validation_error(e)
        assert "Field 'a'" in msg
        assert "and 1 more" in msg


def test_friendly_error_handles_root_path():
    """No location info still produces a sensible message."""
    from pydantic import BaseModel

    from app.jobs.research import _friendly_validation_error

    class Inner(BaseModel):
        pass

    try:
        Inner.model_validate("not a dict")
        assert False, "should have raised"
    except ValidationError as e:
        msg = _friendly_validation_error(e)
        assert msg  # non-empty
        assert isinstance(msg, str)
