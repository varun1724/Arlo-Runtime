"""Verify side hustle prompt template JSON examples match their Pydantic schemas.

Round 2 mirror of ``tests/test_prompt_schema_alignment.py`` for the
side hustle pipeline's 4 research prompts. Each prompt ends with a
literal JSON example showing Claude the expected output shape; these
tests extract the example, populate placeholder strings + enum hints
with realistic values, tile lists to satisfy ``min_length``
constraints, and validate the result against the corresponding schema.

This is the most valuable test in Round 2: if a prompt is edited to
add/rename a field but the schema isn't updated (or vice versa), the
test fails immediately with a clear error pointing at the drifted
field. It is the guard-rail that keeps prompts and schemas in sync.

The helpers (`_get_step`, `_extract_json_example`, `_populate_example`,
`_alignment_check`) are copy-pasted from the startup pipeline test.
Making them generic across both pipelines adds more complexity than
it saves — the duplication is ~80 lines and both files evolve
independently.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from app.workflows.schemas import (
    SideHustleContrarianResult,
    SideHustleFeasibilityResult,
    SideHustleResearchResult,
    SideHustleSynthesisResult,
)
from app.workflows.templates import SIDE_HUSTLE_PIPELINE


# ─────────────────────────────────────────────────────────────────────
# Helpers (mirror tests/test_prompt_schema_alignment.py)
# ─────────────────────────────────────────────────────────────────────


def _get_step(name: str) -> dict:
    for step in SIDE_HUSTLE_PIPELINE["steps"]:
        if step["name"] == name:
            return step
    raise KeyError(f"step {name} not found in side_hustle_pipeline")


def _extract_json_example(template: str) -> str:
    """Pull the literal JSON example from the end of a prompt template.

    The example follows ``OUTPUT: Respond with ONLY valid JSON:`` and
    uses ``{{`` / ``}}`` for literal braces (the template is later
    passed through ``str.format_map``). Extract from the first
    ``{{`` after the marker through the last ``}}`` and un-escape.
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


_ENUM_PATTERN = re.compile(
    r'"([a-zA-Z_][a-zA-Z_0-9]*(?:\s*\|\s*[a-zA-Z_][a-zA-Z_0-9]*)+)(?:\s*—[^"]*)?"'
)

_STRING_PLACEHOLDER = re.compile(r'"string(?:\s*—[^"]*)?"')


def _populate_example(raw_json: str) -> dict[str, Any]:
    """Convert the prompt's JSON example into a validatable dict.

    Steps:
    1. Replace ``"a|b|c"`` enum hints with the first non-"null" option.
    2. Replace remaining ``"string — description"`` placeholders with
       a long placeholder string (>= 20 chars to satisfy min_length
       constraints like ``description: Field(min_length=20)``).
    3. json.loads the result.
    """

    def replace_enum(match: re.Match[str]) -> str:
        options = [o.strip() for o in match.group(1).split("|")]
        for opt in options:
            if opt != "null":
                return f'"{opt}"'
        return f'"{options[0]}"'

    cleaned = _ENUM_PATTERN.sub(replace_enum, raw_json)
    # Round 2 note: the placeholder must be long enough to satisfy the
    # STRICTEST min_length in any side hustle schema. Currently that is
    # executive_summary: Field(min_length=100) on SideHustleSynthesisResult.
    # If the placeholder were shorter, the synthesis alignment test would
    # fail with a 'String should have at least 100 characters' error. If
    # a future schema tightens this further, bump the placeholder here.
    long_placeholder = (
        "a substantially longer placeholder string that satisfies every "
        "min_length constraint currently imposed by any side hustle schema, "
        "including the 100-character minimum on executive_summary"
    )
    cleaned = _STRING_PLACEHOLDER.sub(
        f'"{long_placeholder}"',
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
    example shows only one element, so we tile it to satisfy the
    minimum via ``repeat_list_items`` (key = JSON path, value = count).
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
            assert isinstance(target[last], list) and len(target[last]) >= 1
            # Tile the first element to reach the desired count
            first = target[last][0]
            target[last] = [json.loads(json.dumps(first)) for _ in range(count)]

    schema_cls.model_validate(populated)


# ─────────────────────────────────────────────────────────────────────
# Alignment tests — one per rewritten research step
# ─────────────────────────────────────────────────────────────────────


def test_research_side_hustles_prompt_example_matches_schema():
    """Step 0: opportunities list (min_length=8) and sources_consulted
    (min_length=3) need tiling from the single-item example."""
    _alignment_check(
        "research_side_hustles",
        SideHustleResearchResult,
        repeat_list_items={"opportunities": 8, "sources_consulted": 3},
    )


def test_evaluate_feasibility_prompt_example_matches_schema():
    """Step 1: evaluations list (min_length=5) needs tiling."""
    _alignment_check(
        "evaluate_feasibility",
        SideHustleFeasibilityResult,
        repeat_list_items={"evaluations": 5},
    )


def test_contrarian_analysis_prompt_example_matches_schema():
    """Step 2: analyses list (min_length=3 as of Round 5.A2) needs tiling."""
    _alignment_check(
        "contrarian_analysis",
        SideHustleContrarianResult,
        repeat_list_items={"analyses": 3},
    )


def test_synthesis_and_ranking_prompt_example_matches_schema():
    """Step 3: final_rankings (min_length=2) needs tiling. The
    prompt's example has only 1 ranking; we duplicate it to 2."""
    _alignment_check(
        "synthesis_and_ranking",
        SideHustleSynthesisResult,
        repeat_list_items={"final_rankings": 2},
    )


# ─────────────────────────────────────────────────────────────────────
# Helper sanity checks (mirror startup tests)
# ─────────────────────────────────────────────────────────────────────


def test_extract_helper_handles_double_braces():
    sample = (
        "OUTPUT: Respond with ONLY valid JSON:\n"
        '{{\n  "k": "v"\n}}'
    )
    raw = _extract_json_example(sample)
    assert raw == '{\n  "k": "v"\n}'
    assert json.loads(raw) == {"k": "v"}


def test_populate_helper_picks_first_enum_option():
    raw = '{"verdict": "survives|weakened|killed", "name": "string — desc"}'
    parsed = _populate_example(raw)
    assert parsed["verdict"] == "survives"
    assert "placeholder" in parsed["name"]
    # Round 2: placeholder must satisfy min_length=100 (the strictest
    # side hustle schema constraint, on executive_summary).
    assert len(parsed["name"]) >= 100


def test_populate_helper_handles_long_enum_lists():
    """The Round 1 side hustle prompts have enums with 4+ options
    (e.g. source_type has 5). Verify the helper handles them all."""
    raw = (
        '{"source_type": "stripe_screenshot|indie_hackers_mrr|reddit_with_proof|'
        'youtube_dashboard|other"}'
    )
    parsed = _populate_example(raw)
    assert parsed["source_type"] == "stripe_screenshot"
