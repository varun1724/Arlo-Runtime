"""Render a synthesis result into HTML email body + plaintext + PDF.

Round 5: the approval-gate notification needs a readable document that
the user can consume on their phone. This module takes the validated
synthesis JSON (shape defined by ``SynthesisResult`` in
``app.workflows.schemas``) and produces three outputs:

1. **HTML body** — inline CSS, mobile-friendly, rendered by any modern
   email client. Each ranking is a card with a prominent "Build this
   one" button that links to the signed approval URL.

2. **Plaintext fallback** — a readable text version for clients that
   don't render HTML (rare but exists). Same content, no markup.

3. **PDF bytes** — the same HTML rendered via ``weasyprint`` for
   archival/offline reading. Attached to the email as a fallback so
   the user can save it even if the email itself gets deleted.

The HTML template is a single string constant at the top of the file
for easy editing. No template engine dependency.
"""

from __future__ import annotations

import html
import logging
import uuid
from typing import Any

logger = logging.getLogger("arlo.report_renderer")


# ─────────────────────────────────────────────────────────────────────
# Inline HTML template with mobile-friendly CSS
# ─────────────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlo — Ranked Startup Opportunities</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #1a1a1a;
    background: #f5f5f7;
    margin: 0;
    padding: 16px;
    line-height: 1.5;
  }}
  .container {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px 0; }}
  h2 {{ font-size: 16px; margin: 20px 0 8px 0; color: #555; font-weight: 600; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 20px; }}
  .summary {{
    background: #fff;
    padding: 16px;
    border-radius: 10px;
    border-left: 4px solid #4a6cf7;
    margin-bottom: 20px;
    font-size: 14px;
  }}
  .card {{
    background: #fff;
    padding: 18px 16px;
    border-radius: 10px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .rank {{ color: #4a6cf7; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .name {{ font-size: 18px; font-weight: 700; margin: 2px 0 4px 0; }}
  .liner {{ color: #555; font-size: 14px; margin-bottom: 12px; }}
  .score-row {{
    background: #f0f2fa;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 13px;
    margin: 10px 0;
    font-family: 'SF Mono', Monaco, Menlo, monospace;
  }}
  .total-score {{ font-size: 22px; font-weight: 700; color: #4a6cf7; }}
  .field {{ margin: 10px 0; font-size: 14px; }}
  .field-label {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
  .field-value {{ color: #1a1a1a; margin-top: 2px; }}
  ul.risks {{ margin: 6px 0 0 0; padding-left: 20px; font-size: 13px; color: #666; }}
  .button {{
    display: inline-block;
    background: #4a6cf7;
    color: #ffffff !important;
    text-decoration: none;
    padding: 12px 22px;
    border-radius: 8px;
    font-weight: 600;
    margin-top: 14px;
    font-size: 14px;
  }}
  .skip {{
    display: inline-block;
    color: #888 !important;
    text-decoration: none;
    padding: 12px 22px;
    margin-top: 14px;
    font-size: 13px;
  }}
  .footer {{ color: #aaa; font-size: 11px; text-align: center; margin-top: 24px; }}
  .cost {{ color: #888; font-size: 12px; }}
</style>
</head>
<body>
  <div class="container">
    <h1>Research complete — pick an idea to build</h1>
    <div class="meta">Workflow {workflow_id}</div>
    <div class="cost">{cost_line}</div>

    <div class="summary">
      <strong>Executive summary</strong><br>
      {executive_summary}
    </div>

    <h2>Ranked opportunities</h2>
    {rankings_html}

    <div style="text-align: center;">
      <a href="{skip_link}" class="skip">Skip — end workflow without building</a>
    </div>

    <div class="footer">
      Arlo Runtime · Generated {workflow_id}
    </div>
  </div>
</body>
</html>
"""


_CARD_TEMPLATE = """
<div class="card">
  <div class="rank">Rank #{rank}</div>
  <div class="name">{name}</div>
  <div class="liner">{one_liner}</div>

  <div class="score-row">
    <span class="total-score">{total_score:.1f}</span>/100 &nbsp;·&nbsp;
    timing {market_timing}/10 &nbsp;·&nbsp;
    defensibility {defensibility}/10 &nbsp;·&nbsp;
    feasibility {solo_dev_feasibility}/10 &nbsp;·&nbsp;
    revenue {revenue_potential}/10 &nbsp;·&nbsp;
    evidence {evidence_quality}/10
  </div>

  <div class="field">
    <div class="field-label">What to build</div>
    <div class="field-value">{what_to_build}</div>
  </div>

  <div class="field">
    <div class="field-label">Core user journey</div>
    <div class="field-value">{core_user_journey}</div>
  </div>

  <div class="field">
    <div class="field-label">Tech stack · Build time</div>
    <div class="field-value">{tech_stack} · {build_time_weeks} weeks</div>
  </div>

  <div class="field">
    <div class="field-label">Risky assumption</div>
    <div class="field-value">{risky_assumption}</div>
  </div>

  {risks_block}

  <a href="{approval_link}" class="button">Build this one →</a>
</div>
"""


def _esc(value: Any) -> str:
    """HTML-escape a value, safely handling None and non-strings."""
    if value is None:
        return ""
    return html.escape(str(value))


def _render_rankings_html(
    rankings: list[dict],
    approval_links: dict[int, str],
) -> str:
    """Render the list of ranking cards as HTML."""
    cards: list[str] = []
    for ranking in rankings:
        rank = ranking.get("rank")
        if rank is None:
            continue
        scores = ranking.get("scores") or {}
        mvp = ranking.get("mvp_spec") or {}
        risks = ranking.get("surviving_risks") or []
        risks_html = ""
        if risks:
            risks_items = "".join(f"<li>{_esc(r)}</li>" for r in risks[:5])
            risks_html = (
                f'<div class="field">'
                f'<div class="field-label">Surviving risks</div>'
                f'<ul class="risks">{risks_items}</ul>'
                f'</div>'
            )
        approval_link = approval_links.get(int(rank), "#")

        card = _CARD_TEMPLATE.format(
            rank=_esc(rank),
            name=_esc(ranking.get("name", "Unnamed")),
            one_liner=_esc(ranking.get("one_liner", "")),
            total_score=float(ranking.get("total_score") or 0),
            market_timing=_esc(scores.get("market_timing", "?")),
            defensibility=_esc(scores.get("defensibility", "?")),
            solo_dev_feasibility=_esc(scores.get("solo_dev_feasibility", "?")),
            revenue_potential=_esc(scores.get("revenue_potential", "?")),
            evidence_quality=_esc(scores.get("evidence_quality", "?")),
            what_to_build=_esc(mvp.get("what_to_build", "")),
            core_user_journey=_esc(mvp.get("core_user_journey", "")),
            tech_stack=_esc(mvp.get("tech_stack", "")),
            build_time_weeks=_esc(mvp.get("build_time_weeks", "?")),
            risky_assumption=_esc(mvp.get("risky_assumption", "")),
            risks_block=risks_html,
            approval_link=_esc(approval_link),
        )
        cards.append(card)
    return "\n".join(cards)


def _render_text_fallback(
    synthesis: dict,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None,
) -> str:
    """Plain-text version of the report. Mirrors the HTML but without markup."""
    lines: list[str] = []
    lines.append("ARLO — RANKED STARTUP OPPORTUNITIES")
    lines.append("=" * 50)
    if workflow_cost_usd is not None:
        lines.append(f"Research cost (API-equivalent): ${workflow_cost_usd:.4f}")
    lines.append("")
    summary = synthesis.get("executive_summary", "").strip()
    if summary:
        lines.append("EXECUTIVE SUMMARY")
        lines.append("-" * 50)
        lines.append(summary)
        lines.append("")
    lines.append("RANKED OPPORTUNITIES")
    lines.append("-" * 50)
    for r in synthesis.get("final_rankings") or []:
        rank = r.get("rank")
        if rank is None:
            continue
        scores = r.get("scores") or {}
        mvp = r.get("mvp_spec") or {}
        lines.append(f"\n#{rank}: {r.get('name', 'Unnamed')}")
        lines.append(f"   {r.get('one_liner', '')}")
        lines.append(
            f"   Total: {float(r.get('total_score') or 0):.1f}/100 · "
            f"timing {scores.get('market_timing','?')}/10 · "
            f"defensibility {scores.get('defensibility','?')}/10 · "
            f"feasibility {scores.get('solo_dev_feasibility','?')}/10 · "
            f"revenue {scores.get('revenue_potential','?')}/10"
        )
        lines.append(f"   What: {mvp.get('what_to_build', '')}")
        lines.append(f"   Journey: {mvp.get('core_user_journey', '')}")
        lines.append(f"   Stack: {mvp.get('tech_stack', '')} ({mvp.get('build_time_weeks', '?')} weeks)")
        lines.append(f"   Risky assumption: {mvp.get('risky_assumption', '')}")
        risks = r.get("surviving_risks") or []
        if risks:
            lines.append("   Risks:")
            for risk in risks[:5]:
                lines.append(f"     - {risk}")
        approval_link = approval_links.get(int(rank))
        if approval_link:
            lines.append(f"   BUILD THIS ONE: {approval_link}")
    lines.append("")
    lines.append(f"Skip and end workflow: {skip_link}")
    return "\n".join(lines)


def _render_pdf_bytes(html_body: str) -> bytes:
    """Shared lazy-import weasyprint path. Returns empty bytes on failure."""
    try:
        import weasyprint
        return weasyprint.HTML(string=html_body).write_pdf()
    except Exception:
        logger.exception("PDF rendering failed; returning empty bytes")
        return b""


def render_startup_synthesis_report(
    synthesis: dict,
    workflow_id: uuid.UUID,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None = None,
) -> tuple[str, str, bytes]:
    """Render the startup pipeline synthesis into (html, text, pdf).

    Args:
        synthesis: The parsed SynthesisResult dict (with ``final_rankings``
            and ``executive_summary`` keys). Expects startup pipeline
            shape: each ranking has ``scores``, ``mvp_spec``, etc.
        workflow_id: The workflow UUID (used for footer / subject line).
        approval_links: ``{rank_number: signed_url}`` mapping. Each ranking
            card gets a "Build this one" button linking to its URL.
        skip_link: Signed URL for the "skip without building" option
            (choice=0).
        workflow_cost_usd: Optional cost so far (nullable; shown only when
            present).

    Returns:
        A tuple ``(html_body, text_fallback, pdf_bytes)`` ready to be
        handed to ``send_email``. PDF bytes start with ``%PDF``.
    """
    rankings = synthesis.get("final_rankings") or []
    cost_line = (
        f"Research cost so far (API-equivalent): ${workflow_cost_usd:.4f}"
        if workflow_cost_usd is not None
        else ""
    )
    executive_summary = synthesis.get("executive_summary", "").strip()

    html_body = _HTML_TEMPLATE.format(
        workflow_id=_esc(workflow_id),
        cost_line=_esc(cost_line),
        executive_summary=_esc(executive_summary).replace("\n", "<br>"),
        rankings_html=_render_rankings_html(rankings, approval_links),
        skip_link=_esc(skip_link),
    )
    text_fallback = _render_text_fallback(synthesis, approval_links, skip_link, workflow_cost_usd)
    pdf_bytes = _render_pdf_bytes(html_body)

    return html_body, text_fallback, pdf_bytes


# Round 5.B1: backward-compat alias. Existing callers (notifications.py
# before the B2 dispatcher lands, tests/test_report_renderer.py, etc.)
# import ``render_synthesis_report``. Keep it as a name that points at
# the startup renderer so nothing breaks on module load.
render_synthesis_report = render_startup_synthesis_report


# ─────────────────────────────────────────────────────────────────────
# Side hustle variant (Round 5.B1)
# ─────────────────────────────────────────────────────────────────────
#
# The side hustle synthesis has a completely different inner shape
# from the startup synthesis: no ``scores`` dict, no ``mvp_spec``, no
# ``moats``. Instead each ranking has ``monthly_income_estimate``,
# ``monthly_costs``, ``contrarian_verdict``, ``raw_score``, and an
# ``n8n_workflow_spec`` sub-dict with 8 required fields
# (trigger_node, node_graph, external_credentials, expected_runtime,
# frequency, out_of_scope, success_metric, risky_assumption).
#
# The CSS block is copy-pasted from ``_HTML_TEMPLATE`` trading small
# duplication for simplicity. If the two templates evolve together
# enough to warrant extraction, Round 6 can pull out a ``_BASE_CSS``
# constant that both templates interpolate.


_HTML_TEMPLATE_SIDE_HUSTLE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arlo — Ranked Side Hustles</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #1a1a1a;
    background: #f5f5f7;
    margin: 0;
    padding: 16px;
    line-height: 1.5;
  }}
  .container {{ max-width: 680px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px 0; }}
  h2 {{ font-size: 16px; margin: 20px 0 8px 0; color: #555; font-weight: 600; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 20px; }}
  .summary {{
    background: #fff;
    padding: 16px;
    border-radius: 10px;
    border-left: 4px solid #4a6cf7;
    margin-bottom: 20px;
    font-size: 14px;
  }}
  .card {{
    background: #fff;
    padding: 18px 16px;
    border-radius: 10px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .rank {{ color: #4a6cf7; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .name {{ font-size: 18px; font-weight: 700; margin: 2px 0 4px 0; }}
  .liner {{ color: #555; font-size: 14px; margin-bottom: 12px; }}
  .money-row {{
    background: #f0f2fa;
    border-radius: 6px;
    padding: 10px 12px;
    font-size: 13px;
    margin: 10px 0;
  }}
  .total-score {{ font-size: 22px; font-weight: 700; color: #4a6cf7; }}
  .verdict-survives {{
    display: inline-block;
    background: #d4edda;
    color: #155724;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    margin-left: 8px;
  }}
  .verdict-weakened {{
    display: inline-block;
    background: #fff3cd;
    color: #856404;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    margin-left: 8px;
  }}
  .field {{ margin: 10px 0; font-size: 14px; }}
  .field-label {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }}
  .field-value {{ color: #1a1a1a; margin-top: 2px; }}
  .spec-block {{
    background: #fafbff;
    border: 1px solid #e6e9f5;
    border-radius: 6px;
    padding: 12px 14px;
    margin: 12px 0;
    font-size: 13px;
  }}
  .spec-block .field {{ margin: 6px 0; }}
  ul.risks {{ margin: 6px 0 0 0; padding-left: 20px; font-size: 13px; color: #666; }}
  ul.node-graph {{ margin: 4px 0 0 0; padding-left: 20px; font-size: 13px; color: #555; font-family: 'SF Mono', Monaco, Menlo, monospace; }}
  .button {{
    display: inline-block;
    background: #4a6cf7;
    color: #ffffff !important;
    text-decoration: none;
    padding: 12px 22px;
    border-radius: 8px;
    font-weight: 600;
    margin-top: 14px;
    font-size: 14px;
  }}
  .skip {{
    display: inline-block;
    color: #888 !important;
    text-decoration: none;
    padding: 12px 22px;
    margin-top: 14px;
    font-size: 13px;
  }}
  .footer {{ color: #aaa; font-size: 11px; text-align: center; margin-top: 24px; }}
  .cost {{ color: #888; font-size: 12px; }}
</style>
</head>
<body>
  <div class="container">
    <h1>Research complete — pick a side hustle to automate</h1>
    <div class="meta">Workflow {workflow_id}</div>
    <div class="cost">{cost_line}</div>

    <div class="summary">
      <strong>Executive summary</strong><br>
      {executive_summary}
    </div>

    <h2>Ranked side hustles</h2>
    {rankings_html}

    <div style="text-align: center;">
      <a href="{skip_link}" class="skip">Skip — end workflow without building</a>
    </div>

    <div class="footer">
      Arlo Runtime · Generated {workflow_id}
    </div>
  </div>
</body>
</html>
"""


_CARD_TEMPLATE_SIDE_HUSTLE = """
<div class="card">
  <div class="rank">Rank #{rank}</div>
  <div class="name">{name}{verdict_badge}</div>
  <div class="liner">{one_liner}</div>

  <div class="money-row">
    <span class="total-score">{total_score:.1f}</span>/65 &nbsp;·&nbsp;
    Monthly income: <strong>{monthly_income_estimate}</strong> &nbsp;·&nbsp;
    Monthly costs: <strong>{monthly_costs}</strong>
  </div>

  <div class="field">
    <div class="field-label">Why this beats the next ranking</div>
    <div class="field-value">{head_to_head}</div>
  </div>

  <div class="spec-block">
    <div class="field">
      <div class="field-label">Trigger</div>
      <div class="field-value">{trigger_node}</div>
    </div>
    <div class="field">
      <div class="field-label">Frequency · Expected runtime</div>
      <div class="field-value">{frequency} · {expected_runtime}</div>
    </div>
    <div class="field">
      <div class="field-label">Node graph</div>
      <ul class="node-graph">{node_graph_html}</ul>
    </div>
    <div class="field">
      <div class="field-label">Credentials to configure</div>
      <div class="field-value">{external_credentials}</div>
    </div>
    <div class="field">
      <div class="field-label">Success metric</div>
      <div class="field-value">{success_metric}</div>
    </div>
    <div class="field">
      <div class="field-label">Risky assumption</div>
      <div class="field-value">{risky_assumption}</div>
    </div>
    <div class="field">
      <div class="field-label">Out of scope (v1)</div>
      <div class="field-value">{out_of_scope}</div>
    </div>
  </div>

  {risks_block}

  <a href="{approval_link}" class="button">Build this one →</a>
</div>
"""


def _render_side_hustle_rankings_html(
    rankings: list[dict],
    approval_links: dict[int, str],
) -> str:
    """Render side hustle ranking cards as HTML."""
    cards: list[str] = []
    for ranking in rankings:
        rank = ranking.get("rank")
        if rank is None:
            continue
        spec = ranking.get("n8n_workflow_spec") or {}
        risks = ranking.get("surviving_risks") or []
        risks_html = ""
        if risks:
            risks_items = "".join(f"<li>{_esc(r)}</li>" for r in risks[:5])
            risks_html = (
                f'<div class="field">'
                f'<div class="field-label">Surviving risks</div>'
                f'<ul class="risks">{risks_items}</ul>'
                f'</div>'
            )
        approval_link = approval_links.get(int(rank), "#")

        # Contrarian verdict badge: survives/weakened are the only
        # values that make it into final_rankings (killed is dropped).
        verdict = (ranking.get("contrarian_verdict") or "").lower()
        if verdict == "survives":
            verdict_badge = '<span class="verdict-survives">Survives</span>'
        elif verdict == "weakened":
            verdict_badge = '<span class="verdict-weakened">Weakened</span>'
        else:
            verdict_badge = ""

        # node_graph is a list of {node, role} dicts; render as <li>
        node_graph = spec.get("node_graph") or []
        node_graph_html = "".join(
            f"<li>{_esc(n.get('node', '?'))} — {_esc(n.get('role', ''))}</li>"
            for n in node_graph
            if isinstance(n, dict)
        )
        if not node_graph_html:
            node_graph_html = "<li>(none)</li>"

        credentials = spec.get("external_credentials") or []
        credentials_str = ", ".join(credentials) if credentials else "none"

        out_of_scope = spec.get("out_of_scope") or []
        out_of_scope_str = " · ".join(out_of_scope) if out_of_scope else "—"

        card = _CARD_TEMPLATE_SIDE_HUSTLE.format(
            rank=_esc(rank),
            name=_esc(ranking.get("name", "Unnamed")),
            verdict_badge=verdict_badge,
            one_liner=_esc(ranking.get("one_liner", "")),
            total_score=float(ranking.get("total_score") or 0),
            monthly_income_estimate=_esc(
                ranking.get("monthly_income_estimate", "?")
            ),
            monthly_costs=_esc(ranking.get("monthly_costs", "?")),
            head_to_head=_esc(ranking.get("head_to_head", "")),
            trigger_node=_esc(spec.get("trigger_node", "?")),
            frequency=_esc(spec.get("frequency", "?")),
            expected_runtime=_esc(spec.get("expected_runtime", "?")),
            node_graph_html=node_graph_html,
            external_credentials=_esc(credentials_str),
            success_metric=_esc(spec.get("success_metric", "")),
            risky_assumption=_esc(spec.get("risky_assumption", "")),
            out_of_scope=_esc(out_of_scope_str),
            risks_block=risks_html,
            approval_link=_esc(approval_link),
        )
        cards.append(card)
    return "\n".join(cards)


def _render_side_hustle_text_fallback(
    synthesis: dict,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None,
) -> str:
    """Plain-text side hustle report. Mirrors the HTML structure."""
    lines: list[str] = []
    lines.append("ARLO — RANKED SIDE HUSTLES")
    lines.append("=" * 50)
    if workflow_cost_usd is not None:
        lines.append(f"Research cost (API-equivalent): ${workflow_cost_usd:.4f}")
    lines.append("")
    summary = (synthesis.get("executive_summary") or "").strip()
    if summary:
        lines.append("EXECUTIVE SUMMARY")
        lines.append("-" * 50)
        lines.append(summary)
        lines.append("")
    lines.append("RANKED SIDE HUSTLES")
    lines.append("-" * 50)
    for r in synthesis.get("final_rankings") or []:
        rank = r.get("rank")
        if rank is None:
            continue
        spec = r.get("n8n_workflow_spec") or {}
        lines.append(f"\n#{rank}: {r.get('name', 'Unnamed')} "
                     f"[{(r.get('contrarian_verdict') or '').upper()}]")
        lines.append(f"   {r.get('one_liner', '')}")
        lines.append(
            f"   Score: {float(r.get('total_score') or 0):.1f}/65 · "
            f"income {r.get('monthly_income_estimate', '?')} · "
            f"costs {r.get('monthly_costs', '?')}"
        )
        lines.append(f"   Head-to-head: {r.get('head_to_head', '')}")
        lines.append(f"   Trigger: {spec.get('trigger_node', '?')}")
        lines.append(
            f"   Frequency: {spec.get('frequency', '?')} · "
            f"Runtime: {spec.get('expected_runtime', '?')}"
        )
        node_graph = spec.get("node_graph") or []
        if node_graph:
            lines.append("   Node graph:")
            for n in node_graph:
                if isinstance(n, dict):
                    lines.append(
                        f"     - {n.get('node', '?')} ({n.get('role', '')})"
                    )
        creds = spec.get("external_credentials") or []
        if creds:
            lines.append(f"   Credentials: {', '.join(creds)}")
        lines.append(f"   Success metric: {spec.get('success_metric', '')}")
        lines.append(f"   Risky assumption: {spec.get('risky_assumption', '')}")
        out_of_scope = spec.get("out_of_scope") or []
        if out_of_scope:
            lines.append(f"   Out of scope: {', '.join(out_of_scope)}")
        risks = r.get("surviving_risks") or []
        if risks:
            lines.append("   Surviving risks:")
            for risk in risks[:5]:
                lines.append(f"     - {risk}")
        approval_link = approval_links.get(int(rank))
        if approval_link:
            lines.append(f"   BUILD THIS ONE: {approval_link}")
    lines.append("")
    lines.append(f"Skip and end workflow: {skip_link}")
    return "\n".join(lines)


def render_side_hustle_synthesis_report(
    synthesis: dict,
    workflow_id: uuid.UUID,
    approval_links: dict[int, str],
    skip_link: str,
    workflow_cost_usd: float | None = None,
) -> tuple[str, str, bytes]:
    """Render the side hustle pipeline synthesis into (html, text, pdf).

    Parallel to :func:`render_startup_synthesis_report` but expects
    the side hustle synthesis shape: each ranking has
    ``monthly_income_estimate``, ``monthly_costs``, ``contrarian_verdict``,
    and an ``n8n_workflow_spec`` sub-dict. See the Round 1/2 prompts
    and ``SideHustleSynthesisResult`` schema for the full contract.

    Returns:
        A tuple ``(html_body, text_fallback, pdf_bytes)``. Same shape
        as the startup renderer so the notification dispatcher can
        call either one through the same code path.
    """
    rankings = synthesis.get("final_rankings") or []
    cost_line = (
        f"Research cost so far (API-equivalent): ${workflow_cost_usd:.4f}"
        if workflow_cost_usd is not None
        else ""
    )
    executive_summary = (synthesis.get("executive_summary") or "").strip()

    html_body = _HTML_TEMPLATE_SIDE_HUSTLE.format(
        workflow_id=_esc(workflow_id),
        cost_line=_esc(cost_line),
        executive_summary=_esc(executive_summary).replace("\n", "<br>"),
        rankings_html=_render_side_hustle_rankings_html(rankings, approval_links),
        skip_link=_esc(skip_link),
    )
    text_fallback = _render_side_hustle_text_fallback(
        synthesis, approval_links, skip_link, workflow_cost_usd
    )
    pdf_bytes = _render_pdf_bytes(html_body)

    return html_body, text_fallback, pdf_bytes
