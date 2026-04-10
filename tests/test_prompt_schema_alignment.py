"""Verify prompt template JSON examples match their Pydantic schemas.

Each step in ``startup_idea_pipeline`` has a prompt that ends with a
literal JSON example showing Claude exactly what shape to return. This
test extracts that example, populates its placeholder strings with
realistic values, and validates the result against the corresponding
Pydantic schema in ``app/workflows/schemas.py``.

If a prompt is edited to add/rename a field but the schema is not
updated (or vice versa), this test fails immediately. It is the
guard-rail that prevents Round 1 prompt-quality drift from silently
breaking workflow validation.

The placeholder population is intentionally generous: it picks the
first option from any ``"a|b|c"`` enum string, replaces remaining
``"string"`` placeholders with a literal token, and leaves integers
as-is. The point is not to validate the example as data; it is to
prove the *shape* matches the schema.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import BaseModel

from app.workflows.schemas import (
    ContrarianResult,
    DeepDiveResult,
    LandscapeResult,
    SynthesisResult,
)
from app.workflows.templates import STARTUP_IDEA_PIPELINE


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _get_step(name: str) -> dict:
    for step in STARTUP_IDEA_PIPELINE["steps"]:
        if step["name"] == name:
            return step
    raise KeyError(f"step {name} not found in startup_idea_pipeline")


def _extract_json_example(template: str) -> str:
    """Pull the literal JSON example from the end of a prompt template.

    The example follows ``OUTPUT: Respond with ONLY valid JSON:`` and uses
    ``{{`` / ``}}`` for literal braces (because the template is later run
    through ``str.format_map``). We extract from the first ``{{`` after the
    OUTPUT marker through the last ``}}`` and un-escape the braces.
    """
    marker = "OUTPUT: Respond with ONLY valid JSON:"
    idx = template.find(marker)
    assert idx != -1, "prompt template missing OUTPUT marker"

    after = template[idx + len(marker):]
    start = after.find("{{")
    end = after.rfind("}}")
    assert start != -1 and end != -1 and end > start, "no {{...}} block found"

    raw = after[start: end + 2]
    return raw.replace("{{", "{").replace("}}", "}")


# Match: "a|b|c", "a | b | c" (with optional explanatory tail like "...|null — only set if...")
_ENUM_PATTERN = re.compile(r'"([a-zA-Z_][a-zA-Z_0-9]*(?:\s*\|\s*[a-zA-Z_][a-zA-Z_0-9]*)+)(?:\s*—[^"]*)?"')

# Match a "string" or "string — description" placeholder
_STRING_PLACEHOLDER = re.compile(r'"string(?:\s*—[^"]*)?"')


def _populate_example(raw_json: str) -> dict[str, Any]:
    """Convert the prompt's JSON example into a dict that schemas can validate.

    Steps:
    1. Replace ``"a|b|c"`` enum hints with ``"a"`` (first option). Skip ``"null"``.
    2. Replace remaining ``"string — description"`` placeholders with ``"placeholder"``.
    3. ``json.loads`` the result.
    """

    def replace_enum(match: re.Match[str]) -> str:
        options = [o.strip() for o in match.group(1).split("|")]
        # Pick first non-"null" option as a representative legal value
        for opt in options:
            if opt != "null":
                return f'"{opt}"'
        return f'"{options[0]}"'

    cleaned = _ENUM_PATTERN.sub(replace_enum, raw_json)
    # Round 3 schemas added min_length constraints (e.g. core_user_journey >= 20).
    # The placeholder must be long enough to satisfy the strictest constraint.
    cleaned = _STRING_PLACEHOLDER.sub(
        '"a longer placeholder string that satisfies min_length constraints"',
        cleaned,
    )

    return json.loads(cleaned)


def _alignment_check(
    step_name: str,
    schema_cls: type[BaseModel],
    repeat_list_items: dict[str, int] | None = None,
) -> None:
    """Extract a step's JSON example and validate it against ``schema_cls``.

    Some schemas have ``min_length`` constraints on lists; the JSON
    example shows only one element, so we tile it to satisfy the minimum
    via ``repeat_list_items`` (key = JSON path, value = repeat count).
    """
    template = _get_step(step_name)["prompt_template"]
    raw = _extract_json_example(template)
    populated = _populate_example(raw)

    if repeat_list_items:
        for path, count in repeat_list_items.items():
            target = populated
            keys = path.split(".")
            for key in keys[:-1]:
                target = target[key]
            last = keys[-1]
            assert isinstance(target[last], list) and len(target[last]) == 1
            target[last] = [json.loads(json.dumps(target[last][0])) for _ in range(count)]

    schema_cls.model_validate(populated)


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


def test_landscape_prompt_example_matches_schema():
    _alignment_check(
        "landscape_scan",
        LandscapeResult,
        repeat_list_items={"opportunities": 5, "sources_consulted": 3},
    )


def test_deep_dive_prompt_example_matches_schema():
    _alignment_check(
        "deep_dive",
        DeepDiveResult,
        repeat_list_items={"deep_dive_opportunities": 3},
    )


def test_contrarian_prompt_example_matches_schema():
    _alignment_check(
        "contrarian_analysis",
        ContrarianResult,
        repeat_list_items={"contrarian_analyses": 3},
    )


def test_synthesis_prompt_example_matches_schema():
    # Round 3: SynthesisResult.final_rankings now requires min_length=3.
    _alignment_check(
        "synthesis_and_ranking",
        SynthesisResult,
        repeat_list_items={"final_rankings": 3},
    )


def test_extract_helper_handles_double_braces():
    """Sanity check: the helper correctly un-escapes {{ and }}."""
    sample = (
        "OUTPUT: Respond with ONLY valid JSON:\n"
        '{{\n  "k": "v"\n}}'
    )
    raw = _extract_json_example(sample)
    assert raw == '{\n  "k": "v"\n}'
    parsed = json.loads(raw)
    assert parsed == {"k": "v"}


def test_populate_helper_picks_first_enum_option():
    raw = '{"verdict": "survives|weakened|killed", "name": "string — desc"}'
    parsed = _populate_example(raw)
    assert parsed["verdict"] == "survives"
    # Round 3: placeholder is now a longer string to satisfy min_length constraints.
    assert "placeholder" in parsed["name"]
    assert len(parsed["name"]) >= 20


def test_populate_helper_skips_null_option():
    raw = '{"x": "overlooked|no_demand|null — explanation"}'
    parsed = _populate_example(raw)
    assert parsed["x"] == "overlooked"
