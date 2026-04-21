"""Tests for the cross-run facts cache."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.facts_cache import (
    format_facts_for_prompt,
    get_facts_block,
    load_facts,
)


def test_load_facts_missing_file_returns_empty_dict(tmp_path: Path):
    """A missing file is the first-run case — must degrade silently."""
    missing = tmp_path / "nope.json"
    assert load_facts(str(missing)) == {}


def test_load_facts_empty_file_returns_empty_dict(tmp_path: Path):
    """An empty file (accidentally truncated, disk-space issue, etc.)
    degrades to empty instead of raising."""
    f = tmp_path / "empty.json"
    f.write_text("")
    assert load_facts(str(f)) == {}


def test_load_facts_malformed_json_returns_empty_dict(tmp_path: Path):
    """A broken file must never block workflow creation."""
    f = tmp_path / "broken.json"
    f.write_text("{ this is not json")
    assert load_facts(str(f)) == {}


def test_load_facts_top_level_array_returns_empty_dict(tmp_path: Path):
    """The format demands a top-level object; a top-level array is a
    user mistake and falls back to empty rather than corrupting the
    prompt render."""
    f = tmp_path / "array.json"
    f.write_text(json.dumps(["some", "facts"]))
    assert load_facts(str(f)) == {}


def test_load_facts_valid_file(tmp_path: Path):
    f = tmp_path / "good.json"
    payload = {
        "regulatory_events": [{"name": "FSMA 204", "impact": "forced buy"}],
        "funded_competitors": [{"name": "Anrok", "funding": "$525M"}],
    }
    f.write_text(json.dumps(payload))
    assert load_facts(str(f)) == payload


def test_format_empty_dict_returns_empty_string():
    """A fresh install with no cached facts renders empty (caller can
    decide how to present that)."""
    assert format_facts_for_prompt({}) == ""


def test_format_sections_and_bullets():
    facts = {
        "regulatory_events": [
            {"name": "FSMA 204", "impact": "forced buy moment"},
        ],
        "funded_competitors": [
            {"name": "Anrok", "funding": "$525M", "vertical": "sales tax"},
        ],
    }
    block = format_facts_for_prompt(facts)

    # Section headers present and uppercased with spaces
    assert "## REGULATORY EVENTS" in block
    assert "## FUNDED COMPETITORS" in block

    # Bullet format joins key-value pairs with |
    assert "- name: FSMA 204 | impact: forced buy moment" in block
    assert "- name: Anrok | funding: $525M | vertical: sales tax" in block


def test_format_skips_empty_sections():
    """Sections with no entries don't render a lonely header."""
    facts = {
        "regulatory_events": [{"name": "x"}],
        "dead_playbooks": [],  # empty — skip
    }
    block = format_facts_for_prompt(facts)
    assert "REGULATORY EVENTS" in block
    assert "DEAD PLAYBOOKS" not in block


def test_format_handles_non_list_values_gracefully():
    """Malformed entries (dicts that aren't lists) are skipped rather
    than crashing the render."""
    facts = {"regulatory_events": "not a list"}
    block = format_facts_for_prompt(facts)
    # Skipped — nothing to render
    assert block == ""


def test_format_strips_null_and_empty_values_from_entry():
    """An entry with None, '', or [] values hides those keys so the
    bullet stays readable."""
    facts = {
        "incumbent_moves": [
            {
                "incumbent": "Intuit",
                "event": "Agentic AI launch",
                "date": "2025-07",
                "impact": None,       # skip
                "notes": "",          # skip
                "tags": [],           # skip
            }
        ]
    }
    block = format_facts_for_prompt(facts)
    assert "impact" not in block
    assert "notes" not in block
    assert "tags" not in block
    assert "incumbent: Intuit" in block
    assert "event: Agentic AI launch" in block


def test_get_facts_block_missing_file_is_empty_string(tmp_path: Path):
    """End-to-end: no file → empty prompt block."""
    assert get_facts_block(str(tmp_path / "nope.json")) == ""
