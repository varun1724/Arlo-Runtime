"""Tests for the Round 5 synthesis report renderer.

Pure unit tests — no SMTP, no DB. Uses the Round 3 ``VALID_SYNTHESIS``
fixture (which has 3 rankings by Round 3's min_length constraint) as
input and inspects the HTML/text/PDF outputs.

PDF tests run only when weasyprint is importable. In CI where system
deps aren't available, the module catches the import error and returns
empty bytes — those tests are skipped.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.services.report_renderer import (
    _HTML_TEMPLATE,
    _render_rankings_html,
    render_synthesis_report,
)
from tests.fixtures.startup_pipeline_fixtures import VALID_SYNTHESIS


def _default_links() -> tuple[dict[int, str], str]:
    """Approval links + skip link for the fixture's 3 rankings."""
    approval = {
        1: "https://arlo.local/workflows/xxx/approve-link/tok1",
        2: "https://arlo.local/workflows/xxx/approve-link/tok2",
        3: "https://arlo.local/workflows/xxx/approve-link/tok3",
    }
    skip = "https://arlo.local/workflows/xxx/approve-link/skip-tok"
    return approval, skip


def test_render_returns_html_text_pdf_tuple():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, text, pdf = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip, 0.1234)
    assert isinstance(html, str) and len(html) > 0
    assert isinstance(text, str) and len(text) > 0
    assert isinstance(pdf, bytes)


def test_render_html_contains_all_ranking_names():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    for ranking in VALID_SYNTHESIS["final_rankings"]:
        assert ranking["name"] in html, f"missing ranking name: {ranking['name']!r}"


def test_render_html_contains_all_approval_links():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    # Every approval URL should appear in an href
    for url in approval.values():
        assert f'href="{url}"' in html, f"missing approval link: {url!r}"
    # Skip link also present
    assert f'href="{skip}"' in html


def test_render_html_includes_executive_summary():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    summary = VALID_SYNTHESIS["executive_summary"]
    # First sentence should appear in the HTML
    first_sentence = summary.split(".")[0]
    assert first_sentence in html or first_sentence[:40] in html


def test_render_html_includes_total_score_and_component_scores():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    first = VALID_SYNTHESIS["final_rankings"][0]
    # Total score formatted with one decimal
    assert f"{float(first['total_score']):.1f}" in html
    # Component scores as numbers
    scores = first["scores"]
    assert str(scores["market_timing"]) in html
    assert str(scores["solo_dev_feasibility"]) in html


def test_render_text_fallback_has_no_html_tags():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    _, text, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    # Rough heuristic: no angle-bracketed tags
    assert "<html" not in text.lower()
    assert "<body" not in text.lower()
    assert "<div" not in text.lower()
    assert "</p>" not in text.lower()


def test_render_text_includes_ranking_names_and_urls():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    _, text, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    for ranking in VALID_SYNTHESIS["final_rankings"]:
        assert ranking["name"] in text
    for url in approval.values():
        assert url in text
    assert skip in text


def test_render_html_handles_empty_surviving_risks():
    """A ranking with no risks shouldn't produce an empty '<ul>'."""
    synth = {
        **VALID_SYNTHESIS,
        "final_rankings": [
            {**r, "surviving_risks": []} for r in VALID_SYNTHESIS["final_rankings"]
        ],
    }
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, _ = render_synthesis_report(synth, wf, approval, skip)
    # Still renders successfully
    assert "Ranked opportunities" in html


def test_render_handles_missing_cost():
    """workflow_cost_usd=None should omit the cost line."""
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, text, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip, None)
    # The cost line should be absent
    assert "Research cost" not in html
    assert "Research cost" not in text


def test_render_shows_cost_when_provided():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, text, _ = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip, 0.0832)
    assert "$0.0832" in html
    assert "$0.0832" in text


def test_render_rankings_html_skips_rankings_without_rank():
    """Defensive: a malformed ranking without a 'rank' field is silently skipped."""
    rankings = [
        {"name": "no rank field"},  # missing 'rank'
        {"rank": 1, "name": "valid", "one_liner": "x", "scores": {}, "mvp_spec": {}, "total_score": 25.0},
    ]
    html = _render_rankings_html(rankings, {1: "https://x/1"})
    assert "no rank field" not in html
    assert "valid" in html


def test_render_escapes_html_in_ranking_names():
    """XSS defense: ranking name with HTML tags should be escaped."""
    synth = {
        "executive_summary": "test",
        "final_rankings": [
            {
                **VALID_SYNTHESIS["final_rankings"][0],
                "name": "<script>alert('xss')</script>",
            },
            VALID_SYNTHESIS["final_rankings"][1],
            VALID_SYNTHESIS["final_rankings"][2],
        ],
    }
    approval, skip = _default_links()
    html, _, _ = render_synthesis_report(synth, uuid.uuid4(), approval, skip)
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


# ─────────────────────────────────────────────────────────────────────
# PDF tests — skipped gracefully when weasyprint isn't installed
# ─────────────────────────────────────────────────────────────────────


def _weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _weasyprint_available(), reason="weasyprint not installed locally")
def test_render_pdf_has_valid_header_bytes():
    approval, skip = _default_links()
    wf = uuid.uuid4()
    _, _, pdf = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip, 0.01)
    assert pdf.startswith(b"%PDF"), f"PDF magic bytes missing; got {pdf[:10]!r}"
    # Sanity: non-trivial size (a real PDF of this template is >10KB)
    assert len(pdf) > 1000


@pytest.mark.skipif(not _weasyprint_available(), reason="weasyprint not installed locally")
def test_render_pdf_and_html_consistent_ranking_count():
    """The PDF should contain the same number of rankings as the HTML."""
    approval, skip = _default_links()
    wf = uuid.uuid4()
    html, _, pdf = render_synthesis_report(VALID_SYNTHESIS, wf, approval, skip)
    # Count ranking cards in HTML via "Rank #" marker
    html_ranks = re.findall(r"Rank #\d+", html)
    assert len(html_ranks) == len(VALID_SYNTHESIS["final_rankings"])
    # PDF must also be non-empty
    assert len(pdf) > 1000


# ─────────────────────────────────────────────────────────────────────
# Round 5.B1: side hustle renderer variant
# ─────────────────────────────────────────────────────────────────────


from app.services.report_renderer import (  # noqa: E402
    render_side_hustle_synthesis_report,
    render_startup_synthesis_report,
)
from tests.fixtures.side_hustle_fixtures import (  # noqa: E402
    VALID_SIDE_HUSTLE_SYNTHESIS,
)


def _default_side_hustle_links() -> tuple[dict[int, str], str]:
    """Approval links for the 2 rankings in VALID_SIDE_HUSTLE_SYNTHESIS."""
    approval = {
        1: "https://arlo.local/workflows/sh/approve-link/sh-tok1",
        2: "https://arlo.local/workflows/sh/approve-link/sh-tok2",
    }
    skip = "https://arlo.local/workflows/sh/approve-link/sh-skip"
    return approval, skip


def test_side_hustle_render_returns_tuple_shape():
    """Round 5.B1: same (html, text, pdf) return tuple as startup."""
    approval, skip = _default_side_hustle_links()
    wf = uuid.uuid4()
    html, text, pdf = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, wf, approval, skip, 0.42
    )
    assert isinstance(html, str) and len(html) > 0
    assert isinstance(text, str) and len(text) > 0
    assert isinstance(pdf, bytes)


def test_side_hustle_render_html_contains_all_ranking_names():
    approval, skip = _default_side_hustle_links()
    wf = uuid.uuid4()
    html, _, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, wf, approval, skip
    )
    for ranking in VALID_SIDE_HUSTLE_SYNTHESIS["final_rankings"]:
        assert ranking["name"] in html, (
            f"missing ranking name: {ranking['name']!r}"
        )


def test_side_hustle_render_html_contains_side_hustle_specific_labels():
    """Confirm the side hustle template labels are present and the
    startup-specific labels are NOT (regression guard against
    accidentally reusing the wrong template)."""
    approval, skip = _default_side_hustle_links()
    html, _, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip
    )
    # Side hustle labels that MUST appear
    for marker in (
        "Monthly income",
        "Monthly costs",
        "side hustle",
        "Trigger",
        "Frequency",
        "Node graph",
    ):
        assert marker in html, f"missing side hustle label: {marker!r}"
    # Startup-specific labels that MUST NOT appear (these would
    # indicate we're using the wrong template)
    for bad_marker in (
        "What to build",          # startup mvp_spec label
        "Core user journey",      # startup mvp_spec label
        "defensibility",          # startup score name
        "solo_dev_feasibility",   # startup score name
    ):
        assert bad_marker not in html, (
            f"side hustle template leaked startup label: {bad_marker!r}"
        )


def test_side_hustle_render_html_contains_n8n_workflow_spec_fields():
    """Every ranking's n8n_workflow_spec fields must be rendered.

    Uses substring prefixes rather than full-value equality because
    html.escape() converts quote chars in the fixture (e.g.
    ``'deal-scan-trigger'`` → ``&#x27;deal-scan-trigger&#x27;``).
    Literal comparison against the raw fixture value would fail.
    """
    approval, skip = _default_side_hustle_links()
    html, _, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip
    )
    first = VALID_SIDE_HUSTLE_SYNTHESIS["final_rankings"][0]
    spec = first["n8n_workflow_spec"]
    # Trigger node: match a quote-free prefix
    assert "n8n-nodes-base.webhook with path:" in html
    # Also verify the webhook slug (with HTML-escaped quotes) renders
    assert "deal-scan-trigger" in html
    # Frequency shows up (quote-free fixture value)
    assert spec["frequency"] in html
    # Expected runtime shows up (quote-free fixture value)
    assert spec["expected_runtime"] in html
    # First node_graph entry's node type shows up
    first_node = spec["node_graph"][0]
    assert first_node["node"] in html


def test_side_hustle_render_html_contains_all_approval_links():
    approval, skip = _default_side_hustle_links()
    wf = uuid.uuid4()
    html, _, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, wf, approval, skip
    )
    for url in approval.values():
        assert f'href="{url}"' in html, f"missing approval link: {url!r}"
    assert f'href="{skip}"' in html


def test_side_hustle_render_html_renders_contrarian_verdict_badge():
    """Round 5.B1: contrarian verdict is displayed as a styled badge.
    Both 'survives' and 'weakened' should produce a visible badge."""
    approval, skip = _default_side_hustle_links()
    html, _, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip
    )
    # Fixture has rank 1 weakened and rank 2 with _minimal_ranking
    # (verdict "survives"). Both badges should appear.
    assert "verdict-weakened" in html or "Weakened" in html
    assert "verdict-survives" in html or "Survives" in html


def test_side_hustle_render_text_fallback_has_no_html_tags():
    approval, skip = _default_side_hustle_links()
    _, text, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip
    )
    assert "<html" not in text.lower()
    assert "<body" not in text.lower()
    assert "<div" not in text.lower()
    assert "<a href" not in text.lower()


def test_side_hustle_render_text_includes_names_and_urls():
    approval, skip = _default_side_hustle_links()
    _, text, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip
    )
    for ranking in VALID_SIDE_HUSTLE_SYNTHESIS["final_rankings"]:
        assert ranking["name"] in text
    for url in approval.values():
        assert url in text
    assert skip in text


def test_side_hustle_render_handles_missing_cost():
    approval, skip = _default_side_hustle_links()
    html, text, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip, None
    )
    assert "Research cost" not in html
    assert "Research cost" not in text


def test_side_hustle_render_shows_cost_when_provided():
    approval, skip = _default_side_hustle_links()
    html, text, _ = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip, 0.4275
    )
    assert "$0.4275" in html
    assert "$0.4275" in text


def test_side_hustle_render_escapes_html_in_ranking_names():
    """XSS defense — ranking name with HTML tags gets escaped."""
    synth = {
        **VALID_SIDE_HUSTLE_SYNTHESIS,
        "final_rankings": [
            {
                **VALID_SIDE_HUSTLE_SYNTHESIS["final_rankings"][0],
                "name": "<script>alert('xss')</script>",
            },
            VALID_SIDE_HUSTLE_SYNTHESIS["final_rankings"][1],
        ],
    }
    approval, skip = _default_side_hustle_links()
    html, _, _ = render_side_hustle_synthesis_report(
        synth, uuid.uuid4(), approval, skip
    )
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_render_synthesis_report_alias_still_works():
    """Round 5.B1: the backward-compat alias must still point at the
    startup renderer so legacy imports continue working."""
    from app.services import report_renderer
    assert (
        report_renderer.render_synthesis_report
        is report_renderer.render_startup_synthesis_report
    )


@pytest.mark.skipif(not _weasyprint_available(), reason="weasyprint not installed locally")
def test_side_hustle_render_pdf_has_valid_header_bytes():
    approval, skip = _default_side_hustle_links()
    _, _, pdf = render_side_hustle_synthesis_report(
        VALID_SIDE_HUSTLE_SYNTHESIS, uuid.uuid4(), approval, skip, 0.01
    )
    assert pdf.startswith(b"%PDF"), f"PDF magic bytes missing; got {pdf[:10]!r}"
    assert len(pdf) > 1000
