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


# ─────────────────────────────────────────────────────────────────────
# Round 4: Bug B regression — extract_usage tolerates string token counts
# ─────────────────────────────────────────────────────────────────────


def test_safe_int_helper_handles_int():
    from app.services.claude_runner import _safe_int
    assert _safe_int(42) == 42
    assert _safe_int(0) == 0


def test_safe_int_helper_handles_string():
    from app.services.claude_runner import _safe_int
    assert _safe_int("100") == 100
    assert _safe_int("0") == 0


def test_safe_int_helper_handles_garbage():
    from app.services.claude_runner import _safe_int
    assert _safe_int(None) is None
    assert _safe_int("not a number") is None
    assert _safe_int([]) is None
    assert _safe_int({}) is None
    # bool is a subclass of int but we treat it as not-an-int
    assert _safe_int(True) is None


def test_extract_usage_string_cache_tokens_does_not_crash():
    """Round 4 Bug B: previously, cache token counts as strings would crash
    with TypeError: int + str. Now they're safely coerced via _safe_int."""
    from app.services.claude_runner import extract_usage
    output = {
        "model": "claude-sonnet-4",
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": "200",  # string instead of int
            "cache_read_input_tokens": "50",
        },
    }
    result = extract_usage(output)
    # Should NOT crash — and should sum the cache tokens into input
    assert result["input_tokens"] == 1000 + 200 + 50
    assert result["output_tokens"] == 500
    assert result["estimated_cost_usd"] is not None
    assert result["estimated_cost_usd"] > 0


def test_extract_usage_string_input_and_output_tokens():
    """Even the primary token fields should tolerate string values."""
    from app.services.claude_runner import extract_usage
    output = {
        "model": "claude-sonnet-4",
        "usage": {
            "input_tokens": "5000",
            "output_tokens": "2000",
        },
    }
    result = extract_usage(output)
    assert result["input_tokens"] == 5000
    assert result["output_tokens"] == 2000
    assert result["estimated_cost_usd"] is not None


def test_extract_usage_garbage_token_values_returns_none():
    """If token counts are completely unparseable, fall back to None."""
    from app.services.claude_runner import extract_usage
    output = {
        "usage": {
            "input_tokens": "garbage",
            "output_tokens": [],
        },
    }
    result = extract_usage(output)
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None
    assert result["estimated_cost_usd"] is None


# ─────────────────────────────────────────────────────────────────────
# Round 5.5: _extract_json_payload — Claude preamble tolerance
# ─────────────────────────────────────────────────────────────────────


def test_extract_json_strips_preamble_before_fence():
    """Real production failure: Claude prefixed an English sentence
    before its ```json fence. The previous parser only stripped fences
    at start/end of the cleaned string and choked on 'N' from 'Now'."""
    from app.jobs.research import _extract_json_payload

    raw = (
        "Now I have sufficient data from all sources. Let me compile.\n"
        "\n"
        '```json\n{"market_size": "10B", "key_players": []}\n```\n'
    )
    extracted = _extract_json_payload(raw)
    import json as _json
    parsed = _json.loads(extracted)
    assert parsed["market_size"] == "10B"


def test_extract_json_strips_preamble_no_fence():
    """No fence at all — bare JSON object after preamble text."""
    from app.jobs.research import _extract_json_payload

    raw = "Here is the result.\n{\"a\": 1, \"b\": [2, 3]}\nThanks!"
    extracted = _extract_json_payload(raw)
    import json as _json
    parsed = _json.loads(extracted)
    assert parsed == {"a": 1, "b": [2, 3]}


def test_extract_json_handles_braces_in_strings():
    """The brace-counting fallback must ignore braces inside string
    literals (e.g. ``"price": "$5{...}"``)."""
    from app.jobs.research import _extract_json_payload

    raw = 'preamble {"k": "value with } brace", "n": 1}'
    extracted = _extract_json_payload(raw)
    import json as _json
    parsed = _json.loads(extracted)
    assert parsed["n"] == 1
    assert "}" in parsed["k"]


def test_extract_json_plain_json_passthrough():
    """A clean JSON string with no preamble must still parse."""
    from app.jobs.research import _extract_json_payload

    raw = '{"x": 42}'
    extracted = _extract_json_payload(raw)
    import json as _json
    assert _json.loads(extracted) == {"x": 42}


def test_extract_json_returns_input_when_no_json_found():
    """If neither a fence nor a brace block exists, return the
    stripped input so json.loads fails with a clear error and the
    auto-retry path kicks in."""
    from app.jobs.research import _extract_json_payload

    raw = "  no json at all here  "
    assert _extract_json_payload(raw) == "no json at all here"


# ─────────────────────────────────────────────────────────────────────
# Round 5.6: _sanitize_json_payload — strip Claude's JS-isms
# ─────────────────────────────────────────────────────────────────────


def test_sanitize_strips_trailing_comma_in_object():
    """Real production failure: Claude wrote {..., "x": 1, } which is
    invalid JSON. The error was 'Expecting property name enclosed in
    double quotes' deep in the file."""
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"a": 1, "b": 2,}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"a": 1, "b": 2}


def test_sanitize_strips_trailing_comma_in_array():
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"items": [1, 2, 3,]}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"items": [1, 2, 3]}


def test_sanitize_strips_nested_trailing_commas():
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"outer": {"inner": [1, 2,], "k": "v",},}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"outer": {"inner": [1, 2], "k": "v"}}


def test_sanitize_preserves_commas_inside_strings():
    """A literal comma inside a string value is NOT a trailing comma
    and must not be touched, even if followed by whitespace + closing
    bracket within the same string."""
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"k": "value, with comma"}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"k": "value, with comma"}


def test_sanitize_strips_line_comments():
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{\n  "a": 1, // this is a comment\n  "b": 2\n}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"a": 1, "b": 2}


def test_sanitize_strips_block_comments():
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"a": 1, /* multi\nline\ncomment */ "b": 2}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"a": 1, "b": 2}


def test_sanitize_preserves_slashes_in_strings():
    """URLs and forward slashes inside string values must survive the
    line-comment regex untouched."""
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"url": "https://example.com/path", "n": 1}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"url": "https://example.com/path", "n": 1}


def test_sanitize_handles_escaped_quotes_in_strings():
    """Escaped quotes inside string values must not confuse the
    string-tracking pass."""
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = r'{"q": "she said \"hi\"", "n": 1,}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned)["q"] == 'she said "hi"'


def test_sanitize_noop_on_clean_json():
    """Clean JSON must pass through unchanged."""
    from app.jobs.research import _sanitize_json_payload
    import json as _json

    raw = '{"a": [1, 2, 3], "b": {"c": "d"}}'
    cleaned = _sanitize_json_payload(raw)
    assert _json.loads(cleaned) == {"a": [1, 2, 3], "b": {"c": "d"}}


def test_extract_json_payload_applies_sanitization():
    """Round 5.6 integration: _extract_json_payload should produce
    sanitized output for the bare-brace path."""
    from app.jobs.research import _extract_json_payload
    import json as _json

    raw = 'preamble {"a": 1, "b": [2, 3,],}'
    extracted = _extract_json_payload(raw)
    assert _json.loads(extracted) == {"a": 1, "b": [2, 3]}
